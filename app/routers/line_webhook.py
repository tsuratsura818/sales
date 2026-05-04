import asyncio
import json
import logging
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, HTTPException

from app.database import SessionLocal
from app.models.job_listing import JobListing
from app.services import line_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["line"])


@router.post("/webhook/line")
async def line_webhook(request: Request):
    """LINE Webhookエンドポイント。postbackアクションを受信"""
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    # 署名検証
    if not line_service.verify_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = json.loads(body)

    for event in payload.get("events", []):
        event_type = event.get("type")
        reply_token = event.get("replyToken")

        if event_type == "postback":
            data = parse_qs(event["postback"]["data"])
            action = data.get("action", [None])[0]
            job_id_str = data.get("job_id", [None])[0]

            if not action or not job_id_str:
                continue

            try:
                job_id = int(job_id_str)
            except ValueError:
                continue

            if action == "apply":
                await _handle_apply(job_id, reply_token)
            elif action == "skip":
                await _handle_skip(job_id, reply_token)
            elif action == "confirm_proposal":
                await _handle_confirm_proposal(job_id, reply_token)
            elif action == "regenerate":
                await _handle_regenerate(job_id, reply_token)
            elif action == "mark_applied":
                await _handle_mark_applied(job_id, reply_token)
            elif action == "mark_skipped":
                await _handle_mark_skipped(job_id, reply_token)
            elif action == "regenerate_v2":
                await _handle_regenerate_v2(job_id, reply_token)
            elif action == "mark_replied":
                await _handle_mark_replied(job_id, reply_token)
            elif action == "mark_won":
                await _handle_mark_won(job_id, reply_token)
            elif action == "mark_lost":
                await _handle_mark_lost(job_id, reply_token)
            elif action == "set_amount":
                amount_str = data.get("amount", ["0"])[0]
                await _handle_set_amount(job_id, reply_token, amount_str)

        elif event_type == "message":
            msg = event.get("message", {})
            if msg.get("type") == "text":
                text = msg.get("text", "").strip()
                if text in ("状況", "ステータス", "status"):
                    await _handle_status_check(reply_token)

    return {"status": "ok"}


async def _handle_apply(job_id: int, reply_token: str) -> None:
    """「応募する」ボタンの処理"""
    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        if not job:
            await line_service.reply_text(reply_token, "案件が見つかりませんでした。")
            return

        if job.status == "applied":
            await line_service.reply_text(reply_token, "この案件は既に応募済みです。")
            return

        if job.status == "applying":
            await line_service.reply_text(reply_token, "この案件は現在応募処理中です。")
            return

        job.status = "approved"
        db.commit()

        await line_service.reply_text(
            reply_token,
            f"了解です！\n「{job.title[:30]}」の提案文を生成中...\n確認後に応募します。"
        )

        # バックグラウンドで提案文生成（確認待ち）
        from app.routers.jobs import _apply_to_job
        asyncio.create_task(_apply_to_job(job_id))

    finally:
        db.close()


async def _handle_skip(job_id: int, reply_token: str) -> None:
    """「スキップ」ボタンの処理"""
    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        if not job:
            await line_service.reply_text(reply_token, "案件が見つかりませんでした。")
            return

        job.status = "skipped"
        db.commit()

        await line_service.reply_text(reply_token, "スキップしました。")
    finally:
        db.close()


async def _handle_confirm_proposal(job_id: int, reply_token: str) -> None:
    """「この内容で送信」ボタンの処理"""
    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        if not job:
            await line_service.reply_text(reply_token, "案件が見つかりませんでした。")
            return

        if job.status == "applied":
            await line_service.reply_text(reply_token, "この案件は既に応募済みです。")
            return

        await line_service.reply_text(
            reply_token,
            f"提案文を送信します...\n「{job.title[:30]}」"
        )

        from app.routers.jobs import _submit_application
        asyncio.create_task(_submit_application(job_id))

    finally:
        db.close()


async def _handle_regenerate(job_id: int, reply_token: str) -> None:
    """「再生成」ボタンの処理"""
    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        if not job:
            await line_service.reply_text(reply_token, "案件が見つかりませんでした。")
            return

        job.status = "approved"
        db.commit()

        await line_service.reply_text(
            reply_token,
            f"提案文を再生成します...\n「{job.title[:30]}」"
        )

        from app.routers.jobs import _apply_to_job
        asyncio.create_task(_apply_to_job(job_id))

    finally:
        db.close()


async def _handle_mark_applied(job_id: int, reply_token: str) -> None:
    """「応募完了」ボタン: 手動応募後のマーキング（実送信は伴わない）"""
    from datetime import datetime
    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        if not job:
            await line_service.reply_text(reply_token, "案件が見つかりませんでした。")
            return

        if job.status == "applied":
            await line_service.reply_text(reply_token, "この案件は既に応募完了マーク済みです。")
            return

        job.status = "applied"
        if not job.notified_at:
            job.notified_at = datetime.now()
        # JobApplication 側もマーク
        from app.models.job_application import JobApplication
        application = db.query(JobApplication).filter(JobApplication.job_listing_id == job_id).first()
        if application:
            application.applied_at = datetime.now()
            application.result_status = "submitted"
        db.commit()

        await line_service.reply_text(
            reply_token,
            f"✅ 応募完了マークしました\n「{job.title[:30]}」\n返信が来たら下のボタンで追跡してください。"
        )
        # 追跡ボタンを送信（返信あり/受注/見送り）
        await line_service.push_funnel_buttons(job_id, job.title)
    finally:
        db.close()


async def _handle_mark_replied(job_id: int, reply_token: str) -> None:
    """「返信あり」ボタン"""
    from datetime import datetime
    from app.models.job_application import JobApplication
    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        application = db.query(JobApplication).filter(JobApplication.job_listing_id == job_id).first()
        if not application:
            await line_service.reply_text(reply_token, "応募レコードが見つかりません。")
            return
        application.replied_at = datetime.now()
        application.result_status = "replied"
        db.commit()
        title = job.title if job else f"job_id={job_id}"
        await line_service.reply_text(reply_token, f"💬 返信ありを記録しました\n「{title[:30]}」")
    finally:
        db.close()


async def _handle_mark_won(job_id: int, reply_token: str) -> None:
    """「受注」ボタン: マーク + 金額入力Quick Replyを送信"""
    from datetime import datetime
    from app.models.job_application import JobApplication
    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        application = db.query(JobApplication).filter(JobApplication.job_listing_id == job_id).first()
        if not application:
            await line_service.reply_text(reply_token, "応募レコードが見つかりません。")
            return
        application.won_at = datetime.now()
        application.result_status = "won"
        # 受注なら返信もあったはず（未マークなら同時にセット）
        if not application.replied_at:
            application.replied_at = datetime.now()
        db.commit()
        title = job.title if job else f"job_id={job_id}"
        await line_service.reply_text(reply_token, f"🏆 受注を記録しました\n「{title[:30]}」")
        await line_service.push_amount_quick_reply(job_id, title)
    finally:
        db.close()


async def _handle_mark_lost(job_id: int, reply_token: str) -> None:
    """「見送り」ボタン"""
    from app.models.job_application import JobApplication
    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        application = db.query(JobApplication).filter(JobApplication.job_listing_id == job_id).first()
        if not application:
            await line_service.reply_text(reply_token, "応募レコードが見つかりません。")
            return
        application.result_status = "lost"
        db.commit()
        title = job.title if job else f"job_id={job_id}"
        await line_service.reply_text(reply_token, f"❌ 見送りを記録しました\n「{title[:30]}」")
    finally:
        db.close()


async def _handle_set_amount(job_id: int, reply_token: str, amount_str: str) -> None:
    """受注金額の確定"""
    from app.models.job_application import JobApplication
    db = SessionLocal()
    try:
        try:
            amount = int(amount_str)
        except ValueError:
            amount = 0
        application = db.query(JobApplication).filter(JobApplication.job_listing_id == job_id).first()
        if not application:
            await line_service.reply_text(reply_token, "応募レコードが見つかりません。")
            return
        application.won_amount = amount if amount > 0 else None
        db.commit()
        if amount > 0:
            await line_service.reply_text(reply_token, f"💰 受注金額 {amount:,}円を記録しました")
        else:
            await line_service.reply_text(reply_token, "金額情報をスキップしました")
    finally:
        db.close()


async def _handle_mark_skipped(job_id: int, reply_token: str) -> None:
    """「スキップ」ボタン（v2）"""
    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        if not job:
            await line_service.reply_text(reply_token, "案件が見つかりませんでした。")
            return
        job.status = "skipped"
        db.commit()
        await line_service.reply_text(
            reply_token,
            f"⏭ スキップしました\n「{job.title[:30]}」"
        )
    finally:
        db.close()


async def _handle_regenerate_v2(job_id: int, reply_token: str) -> None:
    """「再生成」ボタン（v2）: review状態で提案文だけ再生成して同じ形式で再送信"""
    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        if not job:
            await line_service.reply_text(reply_token, "案件が見つかりませんでした。")
            return

        if job.status == "applied":
            await line_service.reply_text(reply_token, "この案件は応募済みです。")
            return

        await line_service.reply_text(
            reply_token,
            f"🔄 提案文を再生成中...\n「{job.title[:30]}」"
        )

        from app.routers.jobs import _regenerate_with_new_format
        asyncio.create_task(_regenerate_with_new_format(job_id))
    finally:
        db.close()


async def _handle_status_check(reply_token: str) -> None:
    """「ステータス」テキストで状況を返す"""
    db = SessionLocal()
    try:
        total = db.query(JobListing).count()
        applied = db.query(JobListing).filter(JobListing.status == "applied").count()
        notified = db.query(JobListing).filter(JobListing.status == "notified").count()
        approved = db.query(JobListing).filter(JobListing.status == "approved").count()

        text = (
            f"📊 案件モニター状況:\n"
            f"・総検出: {total}件\n"
            f"・通知済み（返答待ち）: {notified}件\n"
            f"・応募承認済み: {approved}件\n"
            f"・応募完了: {applied}件\n"
            f"\nダッシュボード: http://localhost:8000/jobs"
        )
        await line_service.reply_text(reply_token, text)
    finally:
        db.close()
