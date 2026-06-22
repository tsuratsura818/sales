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


# 案件の納期で「もうすぐ」とみなす日数（今日からN日以内）
PROJECT_SOON_DAYS = 3
# 案件の納期通知の対象外ステータス
_CLOSED_PROJECT_STATUSES = {"完了", "失注"}


async def collect_due_projects() -> tuple[list[dict], list[dict]]:
    """(納期切れ, 納期がもうすぐ=今日〜N日以内) の案件リストを返す（完了/失注は除外）。"""
    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")
    soon = (now + timedelta(days=PROJECT_SOON_DAYS)).strftime("%Y-%m-%d")
    projects = await notion_service.list_projects()
    overdue, soon_due = [], []
    for p in projects:
        end = p.get("end_date")
        if not end or p.get("status") in _CLOSED_PROJECT_STATUSES:
            continue
        if end < today:
            overdue.append(p)
        elif end <= soon:
            soon_due.append(p)
    overdue.sort(key=lambda x: x.get("end_date") or "")
    soon_due.sort(key=lambda x: x.get("end_date") or "")
    return overdue, soon_due


def _format_message(
    overdue: list[dict], due_today: list[dict],
    proj_overdue: list[dict], proj_soon: list[dict],
) -> str | None:
    if not (overdue or due_today or proj_overdue or proj_soon):
        return None
    lines = ["📋 今日のリマインド", ""]

    # --- タスク ---
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

    # --- 案件の納期 ---
    if proj_overdue:
        lines.append(f"📁🔴 案件 納期超過 ({len(proj_overdue)}件)")
        for p in proj_overdue:
            cl = f"（{p['client']}）" if p.get("client") else ""
            lines.append(f"・{p.get('name') or '（無題）'}{cl} 〜{p.get('end_date')}")
        lines.append("")
    if proj_soon:
        lines.append(f"📁🟠 案件 納期間近 ({len(proj_soon)}件)")
        for p in proj_soon:
            cl = f"（{p['client']}）" if p.get("client") else ""
            lines.append(f"・{p.get('name') or '（無題）'}{cl} 〜{p.get('end_date')}")
        lines.append("")

    lines.append("https://sales-6g78.onrender.com/tasks")
    text = "\n".join(lines)
    return text[:4900]


async def send_task_reminder() -> bool:
    """リマインドを送信する。送る対象（タスク or 案件納期）があれば True。"""
    overdue, due_today = await collect_due_tasks()
    proj_overdue, proj_soon = await collect_due_projects()
    msg = _format_message(overdue, due_today, proj_overdue, proj_soon)
    if not msg:
        logger.info("リマインド: 対象なし")
        return False
    await line_service.push_text_message(msg)
    logger.info(
        f"リマインドLINE送信完了: タスク(期限切れ{len(overdue)}/今日{len(due_today)}) "
        f"案件(超過{len(proj_overdue)}/間近{len(proj_soon)})"
    )
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
