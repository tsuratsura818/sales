"""週次レポート自動生成 + LINE送信（毎週月曜 9:00 JST）"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.database import SessionLocal
from app.models.app_settings import AppSettings
from app.services.forecast_service import get_weekly_comparison
from app.services.goal_service import take_daily_snapshot
from app.services.line_service import push_weekly_report

logger = logging.getLogger(__name__)
settings = get_settings()

JST = timezone(timedelta(hours=9))


def _get_last_report_week() -> str | None:
    """DBから週次レポートの最終送信週を取得（Render再起動後も引き継げる）"""
    db = SessionLocal()
    try:
        cfg = db.query(AppSettings).first()
        return getattr(cfg, "weekly_report_last_week", None) if cfg else None
    finally:
        db.close()


def _mark_report_sent(week: str) -> None:
    """週次レポート送信済みをDBに記録（再起動二重送信防止）"""
    db = SessionLocal()
    try:
        cfg = db.query(AppSettings).first()
        if cfg:
            cfg.weekly_report_last_week = week
            db.commit()
    finally:
        db.close()


async def weekly_report_scheduler():
    """毎週月曜9:00 JSTに週次レポートを生成してLINE送信 + 日次スナップショット"""
    logger.info("週次レポートスケジューラー開始")
    await asyncio.sleep(60)  # 起動直後は待機

    while True:
        try:
            now_jst = datetime.now(JST)

            # 日次スナップショット（毎日1回）
            db = None
            try:
                db = SessionLocal()
                take_daily_snapshot(db)
            except Exception as e:
                logger.warning(f"日次スナップショットエラー: {e}")
            finally:
                if db:
                    db.close()

            # 週次レポート（月曜の指定時間を過ぎ、その週がまだ未送信なら送る）
            # >= で判定することで、その時間帯にループが回らなくても取りこぼさない。
            # _last_report_week は DB 永続化しているため Render 再起動後も二重送信しない。
            iso_year, iso_week, _ = now_jst.isocalendar()
            cur_week = f"{iso_year}-W{iso_week:02d}"
            reached = (
                now_jst.weekday() > settings.WEEKLY_REPORT_DAY
                or (now_jst.weekday() == settings.WEEKLY_REPORT_DAY
                    and now_jst.hour >= settings.WEEKLY_REPORT_HOUR_JST)
            )
            if reached and _get_last_report_week() != cur_week:
                logger.info("週次レポート生成開始")
                db = None
                try:
                    db = SessionLocal()
                    report_data = get_weekly_comparison(db)
                    await push_weekly_report(report_data)
                    _mark_report_sent(cur_week)
                    logger.info(f"週次レポート送信完了: {report_data['period']}")
                except Exception as e:
                    logger.error(f"週次レポートエラー: {e}")
                finally:
                    if db:
                        db.close()

        except Exception as e:
            logger.error(f"週次レポートスケジューラーエラー: {e}")

        # 1時間ごとにチェック
        await asyncio.sleep(3600)
