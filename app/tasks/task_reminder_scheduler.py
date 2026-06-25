"""タスク期限リマインド: 当日期日/期限切れのNotionタスクを毎朝LINE送信"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.database import SessionLocal
from app.models.app_settings import AppSettings
from app.services import notion_service, line_service

logger = logging.getLogger(__name__)
settings = get_settings()
JST = timezone(timedelta(hours=9))


def _get_settings_from_db() -> AppSettings | None:
    db = SessionLocal()
    try:
        return db.query(AppSettings).first()
    finally:
        db.close()


async def collect_due_tasks() -> tuple[list[dict], list[dict]]:
    """(期限切れ, 今日が期日) のタスクリストを返す（完了は除外）。"""
    today = datetime.now(JST).strftime("%Y-%m-%d")
    tasks = await notion_service.list_tasks()
    overdue, due_today = [], []
    for t in tasks:
        due = t.get("due_date")
        if not due or t.get("status") == "完了":
            continue
        if due < today:
            overdue.append(t)
        elif due == today:
            due_today.append(t)
    overdue.sort(key=lambda x: x.get("due_date") or "")
    return overdue, due_today


def _format_message(overdue: list[dict], due_today: list[dict]) -> str | None:
    if not (overdue or due_today):
        return None
    lines = ["📋 今日のタスクリマインド", ""]

    if overdue:
        lines.append(f"🔴 タスク期限切れ ({len(overdue)}件)")
        for t in overdue:
            pr = f"[{t['priority']}] " if t.get("priority") else ""
            lines.append(f"・{pr}{t.get('name') or '（無題）'}（{t.get('due_date')}）")
        lines.append("")
    if due_today:
        lines.append(f"🟡 タスク今日が期日 ({len(due_today)}件)")
        for t in due_today:
            pr = f"[{t['priority']}] " if t.get("priority") else ""
            lines.append(f"・{pr}{t.get('name') or '（無題）'}")
        lines.append("")

    lines.append("https://sales-6g78.onrender.com/tasks")
    text = "\n".join(lines)
    return text[:4900]


async def send_task_reminder() -> bool:
    """タスク期限リマインドを送信する。送る対象があれば True。"""
    overdue, due_today = await collect_due_tasks()
    msg = _format_message(overdue, due_today)
    if not msg:
        logger.info("リマインド: 対象なし")
        return False
    await line_service.push_text_message(msg)
    logger.info(f"タスクリマインドLINE送信完了: 期限切れ{len(overdue)}/今日{len(due_today)}")
    return True


async def task_reminder_scheduler() -> None:
    """毎朝指定時刻にタスク期限リマインドをLINE送信する"""
    await asyncio.sleep(25)

    if not settings.LINE_CHANNEL_ACCESS_TOKEN or not settings.LINE_USER_ID:
        logger.warning("LINE未設定のため、タスクリマインドスケジューラをスキップ")
        return

    logger.info("タスクリマインドスケジューラ開始（DB設定で有効/無効を制御）")

    while True:
        try:
            app_cfg = _get_settings_from_db()
            if not app_cfg or not getattr(app_cfg, "task_reminder_enabled", False):
                await asyncio.sleep(60)
                continue

            target_hour = getattr(app_cfg, "task_reminder_hour_jst", 8)
            now_jst = datetime.now(JST)
            target_time = now_jst.replace(hour=target_hour, minute=0, second=0, microsecond=0)
            if now_jst >= target_time:
                target_time += timedelta(days=1)

            wait_seconds = (target_time - now_jst).total_seconds()
            logger.info(
                f"次回タスクリマインド: {target_time.strftime('%Y-%m-%d %H:%M')} JST "
                f"({wait_seconds / 3600:.1f}時間後)"
            )
            await asyncio.sleep(min(wait_seconds, 3600))

            app_cfg = _get_settings_from_db()
            if not app_cfg or not getattr(app_cfg, "task_reminder_enabled", False):
                continue

            now_jst = datetime.now(JST)
            if now_jst.hour == getattr(app_cfg, "task_reminder_hour_jst", 8):
                await send_task_reminder()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"タスクリマインドスケジューラエラー: {e}")
            await asyncio.sleep(3600)
