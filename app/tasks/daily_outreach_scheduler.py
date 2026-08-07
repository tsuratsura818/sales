"""日次自動アウトリーチ: 毎日きまった時刻に新規の営業メールを送るところまで自動化する。

週次アウトリーチ(`weekly_outreach_scheduler`)が「リストを作ってLINE通知、送信は手動」
なのに対し、こちらは送信まで通す:

  1) リスト収集     … 無料スクレイパー(category コレクター)で新規企業を集める
  2) サイト分析      … HTML を読んで課題を検出（外部API不要）
  3) 提案文生成      … Mac 常駐のローカル Claude（定額サブスク）で1社ずつ個別生成
  4) キャンペーン投入 … MailForge に contacts + campaign_contacts(queued) を作成
  5) 送信開始        … campaign を status=sending にして MailForge の送信cronに任せる
  6) LINE 通知       … 実行結果を報告

【コストについて】
このタスクは従量課金の経路を一切使わない。
  - 収集: category コレクター = HTML スクレイピング（SerpAPI は使わない）
  - 生成: ローカル Claude（CLI もしくは Mac 常駐ブリッジ）= 定額サブスク枠
  - 送信: MailForge の SMTP = 自前アカウント
SerpAPI を使う google コレクターは従量課金なので `DAILY_SOURCES` から除外している。

【安全弁】
  - 既定は無効(`daily_outreach_enabled=False`)。/today のトグルで明示的にONにする
  - 1日の送信上限 `daily_outreach_daily_cap`（既定20件）
  - 配信停止リスト(suppression)に載っている宛先は除外
  - 送信済みは `PipelineResult.queued_at` で記録し、二重送信しない
  - 同日中の二重実行は `daily_outreach_last_date` でガード
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.database import SessionLocal
from app.models.app_settings import AppSettings
from app.models.pipeline import PipelineRun, PipelineResult
from app.services import line_service
from app.services import mailforge_client as mf
from app.services.suppression_service import is_suppressed

logger = logging.getLogger(__name__)
settings = get_settings()
JST = timezone(timedelta(hours=9))

BASE_URL = "https://sales-6g78.onrender.com"

# 収集は無料スクレイパーのみ。google(SerpAPI=従量課金)は使わない。
DAILY_SOURCES = ["category"]
CATEGORY_ROTATION = ["A", "B", "C", "D"]
# 1日分の収集量。Render無料枠で時間内に終わる程度に抑える。
MAX_QUERIES_PER_CATEGORY = 15
MAX_URLS_PER_CATEGORY = 40
# 1日にあたる都道府県の数（全47件を日ごとにスライドさせる）
PREFS_PER_DAY = 6
# 送信対象にするランク
SEND_RANKS = ("S", "A")

# 送信ウィンドウ（MailForge 側の送信cronが参照する）
SEND_START_TIME = "09:00"
SEND_END_TIME = "18:00"
SEND_DAYS = [1, 2, 3, 4, 5]
MIN_INTERVAL_SEC = 120
MAX_INTERVAL_SEC = 300


def _get_cfg() -> AppSettings | None:
    db = SessionLocal()
    try:
        return db.query(AppSettings).first()
    finally:
        db.close()


def _mark_run(date_str: str) -> None:
    db = SessionLocal()
    try:
        cfg = db.query(AppSettings).first()
        if cfg:
            cfg.daily_outreach_last_date = date_str
            db.commit()
    finally:
        db.close()


def _stock_query(db):
    """まだ送っていない、提案文が揃った送信可能リードのクエリ"""
    return (
        db.query(PipelineResult)
        .filter(
            PipelineResult.queued_at.is_(None),
            PipelineResult.email.isnot(None),
            PipelineResult.personalized_subject.isnot(None),
            PipelineResult.personalized_body.isnot(None),
            PipelineResult.rank.in_(SEND_RANKS),
        )
        .order_by(PipelineResult.score.desc(), PipelineResult.id)
    )


async def _collect(day_index: int) -> int:
    """1日分のリード収集を回す。収集できた件数を返す。

    カテゴリ(A〜D)と都道府県を日ごとにローテーションさせて、毎日同じ母集団を
    掘り返さないようにする。category モードで実際に検索クエリを変えるのは
    この2つ（runner の keyword_limit/offset は yahoo/rakuten 等の
    キーワード系コレクター用で、category コレクターには効かない）。
    """
    from app.services.pipeline.runner import run_pipeline
    from app.services.pipeline.category_collector import PREFECTURES

    category = CATEGORY_ROTATION[day_index % len(CATEGORY_ROTATION)]
    # 全都道府県を PREFS_PER_DAY 件ずつスライドさせながら回す
    offset = (day_index * PREFS_PER_DAY) % len(PREFECTURES)
    prefs = [PREFECTURES[(offset + i) % len(PREFECTURES)] for i in range(PREFS_PER_DAY)]

    category_config = {
        "categories": [category],
        "prefectures": prefs,
        "max_queries_per_category": MAX_QUERIES_PER_CATEGORY,
        "max_urls_per_category": MAX_URLS_PER_CATEGORY,
        "generate_proposals": True,  # ローカルClaudeで個別提案文まで作る
    }

    db = SessionLocal()
    try:
        # 既に走っているパイプラインがあれば重ねない
        running = db.query(PipelineRun).filter(PipelineRun.status == "running").first()
        if running:
            logger.warning(f"パイプライン実行中のため収集をスキップ: run_id={running.id}")
            return 0

        run = PipelineRun(
            sources=json.dumps(DAILY_SOURCES),
            keywords_count=0,
            skip_mx=1,
            status="pending",
            mode="category",
            category_config=json.dumps(category_config, ensure_ascii=False),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    logger.info(f"日次アウトリーチ: 収集開始 run_id={run_id} category={category}")
    await run_pipeline(run_id)

    db = SessionLocal()
    try:
        run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
        found = run.total_found if run else 0
        if run and run.status == "failed":
            logger.error(f"日次アウトリーチ: 収集失敗 {run.error_message}")
    finally:
        db.close()
    return found


def _pick_targets(cap: int) -> list[dict]:
    """送信対象を上限まで選ぶ。配信停止リストに載っている宛先は除外する。

    セッションを跨いで使うので ORM オブジェクトではなく dict にして返す。
    """
    db = SessionLocal()
    try:
        picked: list[dict] = []
        seen_emails: set[str] = set()
        # 除外分を見込んで多めに取る
        for r in _stock_query(db).limit(cap * 3).all():
            if len(picked) >= cap:
                break
            email = (r.email or "").strip().lower()
            if not email or email in seen_emails:
                continue
            if is_suppressed(email, db):
                logger.info(f"配信停止リストのためスキップ: {email}")
                continue
            seen_emails.add(email)
            picked.append({
                "id": r.id,
                "email": r.email,
                "company": r.company or "",
                "industry": r.industry or "",
                "website": r.website or "",
                "platform": r.platform or "",
                "ec_status": r.ec_status or "",
                "category": r.category or "",
                "rank": r.rank or "",
                "score": r.score or 0,
                "source": r.source or "",
                "subject": r.personalized_subject,
                "body": r.personalized_body,
            })
        return picked
    finally:
        db.close()


def _push_to_mailforge(targets: list[dict], campaign_name: str) -> dict:
    """MailForge に contacts を upsert → キャンペーン作成 → 送信開始。

    campaign_contacts は status='queued' で投入するので MailForge 側の
    AI生成cron はスキップされ、こちらで作った提案文がそのまま配信される。
    同期I/Oなので呼び出し側で to_thread すること。
    """
    contacts_payload = [
        {
            "email": t["email"],
            "company_name": t["company"],
            "industry": t["industry"],
            "website_url": t["website"],
            "notes": " / ".join(x for x in (t["platform"], t["ec_status"]) if x),
            "custom_fields": {
                "category": t["category"],
                "rank": t["rank"],
                "score": str(t["score"]),
                "source": t["source"],
                "auto": "daily_outreach",
            },
        }
        for t in targets
    ]
    upsert_result = mf.upsert_contacts(contacts_payload)
    email_to_id = upsert_result.get("email_to_id", {})
    if not email_to_id:
        return {"error": f"contacts upsert 失敗: {upsert_result}", "sent": 0}

    campaign = mf.create_campaign({
        "name": campaign_name,
        "status": "sending",  # レビューを挟まずそのまま配信に乗せる
        "sender_name": "西川",
        "subject_template": "(個別生成済み)",
        "body_template": "(個別生成済み)",
        "send_start_time": SEND_START_TIME,
        "send_end_time": SEND_END_TIME,
        "send_days": SEND_DAYS,
        "min_interval_sec": MIN_INTERVAL_SEC,
        "max_interval_sec": MAX_INTERVAL_SEC,
        "total_contacts": 0,
    })
    if not campaign or not campaign.get("id"):
        return {"error": f"campaign 作成失敗: {campaign}", "sent": 0}
    campaign_id = campaign["id"]

    cc_items = []
    queued_ids = []
    for t in targets:
        cid = email_to_id.get(t["email"].lower())
        if not cid:
            continue
        cc_items.append({
            "contact_id": cid,
            "personalized_subject": t["subject"],
            "personalized_body": t["body"],
        })
        queued_ids.append(t["id"])

    cc_result = mf.create_campaign_contacts(campaign_id, cc_items)
    inserted = cc_result.get("inserted", 0)
    if inserted > 0:
        mf.update_campaign(campaign_id, {"total_contacts": inserted})
    else:
        # 1件も入らなかったキャンペーンは動かさない
        mf.update_campaign(campaign_id, {"status": "cancelled"})

    return {
        "campaign_id": campaign_id,
        "sent": inserted,
        "queued_ids": queued_ids if inserted > 0 else [],
        "error": cc_result.get("error"),
    }


def _mark_queued(result_ids: list[int], campaign_id: str) -> None:
    """送信キューに載せたリードに印をつけて二重送信を防ぐ"""
    if not result_ids:
        return
    db = SessionLocal()
    try:
        now = datetime.now(JST).replace(tzinfo=None)
        for r in db.query(PipelineResult).filter(PipelineResult.id.in_(result_ids)).all():
            r.queued_at = now
            r.campaign_id = campaign_id
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"queued_at 記録エラー: {e}")
    finally:
        db.close()


async def run_daily_outreach() -> dict:
    """日次アウトリーチを1回実行。収集→提案文→キャンペーン→送信開始まで。"""
    from app.services import local_claude

    cfg = _get_cfg()
    cap = (getattr(cfg, "daily_outreach_daily_cap", 20) or 20) if cfg else 20
    if cap <= 0:
        return {"started": False, "reason": "送信上限が0", "sent": 0}

    now = datetime.now(JST)
    day_index = now.timetuple().tm_yday

    # 提案文はローカルClaude(定額)でしか作らない。使えないなら課金経路に
    # 落ちるのではなく、何もせず通知して終わる。
    # is_available() は subprocess + HTTP を叩くのでイベントループを塞がない
    if not await asyncio.to_thread(local_claude.is_available):
        await _notify_text(
            "⚠️ 日次アウトリーチを中止しました\n\n"
            "ローカルClaude（Mac常駐ブリッジ）に接続できません。\n"
            "提案文が作れないため収集・送信とも行いませんでした。\n\n"
            f"状態確認: {BASE_URL}/status"
        )
        logger.error("日次アウトリーチ: ローカルClaude利用不可のため中止")
        return {"started": False, "reason": "local_claude 利用不可", "sent": 0}

    # 在庫（提案文まで揃った未送信リード）が足りなければ収集する
    db = SessionLocal()
    try:
        stock = _stock_query(db).count()
    finally:
        db.close()

    collected = 0
    if stock < cap:
        logger.info(f"日次アウトリーチ: 在庫{stock}件 < 上限{cap}件 → 収集を実行")
        try:
            collected = await _collect(day_index)
        except Exception as e:
            logger.exception(f"日次アウトリーチ: 収集エラー: {e}")
    else:
        logger.info(f"日次アウトリーチ: 在庫{stock}件で足りるため収集はスキップ")

    targets = _pick_targets(cap)
    if not targets:
        await _notify_text(
            "📭 日次アウトリーチ: 送信できる新規リードがありませんでした\n\n"
            f"・今回の収集: {collected}件\n"
            "・提案文まで揃った未送信リード: 0件\n\n"
            f"{BASE_URL}/pipeline で状況を確認してください。"
        )
        return {"started": True, "collected": collected, "sent": 0}

    campaign_name = f"日次アウトリーチ {now.strftime('%Y-%m-%d')}"
    try:
        result = await asyncio.to_thread(_push_to_mailforge, targets, campaign_name)
    except Exception as e:
        logger.exception(f"日次アウトリーチ: MailForge投入エラー: {e}")
        await _notify_text(f"⚠️ 日次アウトリーチ: MailForge投入に失敗しました\n{str(e)[:300]}")
        return {"started": True, "collected": collected, "sent": 0, "error": str(e)}

    sent = result.get("sent", 0)
    if result.get("error"):
        logger.error(f"日次アウトリーチ: {result['error']}")
    if sent > 0:
        _mark_queued(result.get("queued_ids", []), result["campaign_id"])

    await _notify(collected, sent, cap, result.get("campaign_id"), result.get("error"))
    return {
        "started": True,
        "collected": collected,
        "sent": sent,
        "campaign_id": result.get("campaign_id"),
    }


async def _notify_text(text: str) -> None:
    if not (settings.LINE_CHANNEL_ACCESS_TOKEN and settings.LINE_USER_ID):
        return
    try:
        await line_service.push_text_message(text[:4900])
    except Exception as e:
        logger.error(f"日次アウトリーチ通知エラー: {e}")


async def _notify(collected: int, sent: int, cap: int, campaign_id: str | None, error: str | None) -> None:
    lines = [
        "📨 本日の営業メールを送信キューに投入しました",
        "",
        f"・新規収集: {collected}件",
        f"・送信: {sent}件（上限 {cap}件/日）",
    ]
    if error:
        lines.append(f"・警告: {error[:200]}")
    if campaign_id:
        lines += ["", f"{BASE_URL}/mail/campaigns/{campaign_id}"]
    await _notify_text("\n".join(lines))
    logger.info(f"日次アウトリーチ完了: 収集{collected}件 / 送信{sent}件")


async def daily_outreach_scheduler() -> None:
    """10分ごとにチェックし、指定時刻を過ぎていてその日が未実行なら実行する。"""
    await asyncio.sleep(60)
    logger.info("日次アウトリーチスケジューラ開始（DB設定で有効/無効を制御）")

    while True:
        try:
            cfg = _get_cfg()
            if cfg and getattr(cfg, "daily_outreach_enabled", False):
                now = datetime.now(JST)
                today = now.strftime("%Y-%m-%d")
                target_hh = getattr(cfg, "daily_outreach_hour_jst", 10)
                weekdays_only = getattr(cfg, "daily_outreach_weekdays_only", True)
                last_date = getattr(cfg, "daily_outreach_last_date", None)

                is_weekend = now.weekday() >= 5
                if weekdays_only and is_weekend:
                    pass  # 土日は送らない
                elif last_date != today and now.hour >= target_hh:
                    # 先に「実行済み」を立ててから走らせる（長い処理中の二重起動防止）
                    _mark_run(today)
                    try:
                        await run_daily_outreach()
                    except Exception as e:
                        logger.exception(f"日次アウトリーチ実行エラー: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"日次アウトリーチスケジューラエラー: {e}")
        await asyncio.sleep(600)
