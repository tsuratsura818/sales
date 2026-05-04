"""クライアントサイトの月次健康診断スケジューラ

毎月1日 4:00 JST に全アクティブなクライアントサイトを順次チェック。
critical/warning が出たら LINE 通知。
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models.client_site import ClientSite
from app.services.health_check_service import check_and_save, format_alert_message
from app.services.line_service import push_text_message

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))

# 1日1回しか走らないようフラグ
_last_run_date: str | None = None


async def health_check_scheduler():
    logger.info("月次健康診断スケジューラ開始")
    await asyncio.sleep(120)  # 起動直後待機

    while True:
        try:
            now_jst = datetime.now(JST)
            today_key = now_jst.strftime("%Y-%m-%d")
            global _last_run_date

            # 毎月1日の4:00台に1回だけ実行
            if (
                now_jst.day == 1
                and now_jst.hour == 4
                and _last_run_date != today_key
            ):
                logger.info("月次健康診断 開始")
                _last_run_date = today_key
                await _run_all()
                logger.info("月次健康診断 完了")
        except Exception as e:
            logger.exception(f"health_check_scheduler error: {e}")

        await asyncio.sleep(300)  # 5分間隔でチェック


async def _run_all():
    """全アクティブなクライアントサイトをチェック"""
    db = SessionLocal()
    try:
        sites = db.query(ClientSite).filter(ClientSite.is_active == True).all()  # noqa: E712
        logger.info(f"対象 {len(sites)}サイト")

        total = len(sites)
        critical_count = 0
        warning_count = 0
        ok_count = 0
        critical_alerts: list[str] = []

        for i, site in enumerate(sites):
            try:
                record = await check_and_save(site, db)
                if record.status == "critical":
                    critical_count += 1
                    critical_alerts.append(format_alert_message(site, record))
                elif record.status == "warning":
                    warning_count += 1
                else:
                    ok_count += 1
            except Exception as e:
                logger.error(f"check failed: {site.url} : {e}")

            # CWに連打しないよう間隔を空ける
            if i < total - 1:
                await asyncio.sleep(5)

        # サマリー通知
        summary = (
            f"📊 月次健康診断サマリー\n"
            f"対象: {total}サイト\n"
            f"🔴 Critical: {critical_count}件\n"
            f"🟡 Warning: {warning_count}件\n"
            f"🟢 OK: {ok_count}件"
        )
        await push_text_message(summary)

        # critical の詳細を逐次送信（最大10件）
        for alert in critical_alerts[:10]:
            await push_text_message(alert)
            await asyncio.sleep(1)
    finally:
        db.close()


async def run_now() -> dict:
    """API/UI からの手動実行用"""
    await _run_all()
    return {"success": True}
