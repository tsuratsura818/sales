"""毎朝の自動スケジュール立案 + LINE送信"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.database import SessionLocal
from app.models.daily_plan import DailyPlan
from app.models.app_settings import AppSettings
from app.services import daily_planner, line_service

logger = logging.getLogger(__name__)
settings = get_settings()
JST = timezone(timedelta(hours=9))


def _get_settings_from_db() -> AppSettings | None:
    """DBから設定を取得"""
    db = SessionLocal()
    try:
        return db.query(AppSettings).first()
    finally:
        db.close()


async def daily_plan_scheduler() -> None:
    """毎朝指定時刻にスケジュールを生成しLINEに送信する"""
    await asyncio.sleep(20)

    if not settings.LINE_CHANNEL_ACCESS_TOKEN or not settings.LINE_USER_ID:
        logger.warning("LINE未設定のため、日次プランスケジューラをスキップ")
        return

    logger.info("日次プランスケジューラ開始（DB設定で有効/無効を制御）")

    while True:
        try:
            app_cfg = _get_settings_from_db()
            if not app_cfg or not app_cfg.daily_plan_enabled:
                logger.info("日次プラン自動送信: OFF — 60秒後に再チェック")
                await asyncio.sleep(60)
                continue

            target_hour = app_cfg.daily_plan_hour_jst
            now_jst = datetime.now(JST)

            target_time = now_jst.replace(
                hour=target_hour, minute=0, second=0, microsecond=0
            )
            if now_jst >= target_time:
                target_time += timedelta(days=1)

            wait_seconds = (target_time - now_jst).total_seconds()
            logger.info(
                f"次回プラン生成: {target_time.strftime('%Y-%m-%d %H:%M')} JST "
                f"({wait_seconds / 3600:.1f}時間後)"
            )
            await asyncio.sleep(min(wait_seconds, 3600))

            # 再チェック（待機中にOFFにされた場合）
            app_cfg = _get_settings_from_db()
            if not app_cfg or not app_cfg.daily_plan_enabled:
                continue

            now_jst = datetime.now(JST)
            if now_jst.hour == app_cfg.daily_plan_hour_jst:
                await _generate_and_send()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"日次プランスケジューラエラー: {e}")
            await asyncio.sleep(3600)


async def _generate_and_send() -> None:
    """プラン生成 + DB保存 + LINE送信"""
    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    logger.info(f"日次プラン自動生成開始: {today_str}")

    try:
        context = await daily_planner.gather_context()
        plan = await daily_planner.generate_daily_plan(context)

        db = SessionLocal()
        try:
            record = DailyPlan(
                plan_date=today_str,
                plan_json=json.dumps(plan, ensure_ascii=False),
                context_json=json.dumps(context, ensure_ascii=False, default=str),
                source="scheduled",
                line_sent=1,
            )
            db.add(record)
            db.commit()
        finally:
            db.close()

        text = daily_planner.format_plan_for_line(plan)
        await line_service.push_text_message(text)
        logger.info(f"日次プランLINE送信完了: {today_str}")

    except Exception as e:
        logger.error(f"日次プラン生成/送信失敗: {e}")
