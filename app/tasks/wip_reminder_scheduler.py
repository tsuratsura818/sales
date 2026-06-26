"""進行中タスクの残リマインド: 毎日指定時刻(既定9:05)に「進行中」のままのタスクをLINE通知。

朝9時の期限を過ぎても進行中のままのタスクを知らせて、やり残しを防ぐ。
1日1回だけ送る（last_sent 日付で管理）。
"""

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


def _get_cfg() -> AppSettings | None:
    db = SessionLocal()
    try:
        return db.query(AppSettings).first()
    finally:
        db.close()


async def collect_wip_tasks() -> list[dict]:
    """「進行中」ステータスのタスクを取得。"""
    return await notion_service.list_tasks(status="進行中")


def _format_message(tasks: list[dict]) -> str | None:
    if not tasks:
        return None
    # 優先度（高→中→低）→期日 で並べる
    order = {"高": 0, "中": 1, "低": 2}
    tasks = sorted(tasks, key=lambda t: (order.get(t.get("priority"), 9), t.get("due_date") or "9999"))
    lines = ["🔔 進行中タスクのリマインド", "", f"まだ「進行中」のタスクが {len(tasks)}件 あります:"]
    for t in tasks:
        pr = f"[{t['priority']}] " if t.get("priority") else ""
        due = f"（〜{t['due_date']}）" if t.get("due_date") else ""
        lines.append(f"・{pr}{t.get('name') or '（無題）'}{due}")
    lines.append("")
    lines.append("https://sales-6g78.onrender.com/tasks")
    return "\n".join(lines)[:4900]


async def send_wip_reminder() -> bool:
    """進行中タスクのリマインドを送信。対象があれば True。"""
    tasks = await collect_wip_tasks()
    msg = _format_message(tasks)
    if not msg:
        logger.info("進行中リマインド: 対象なし")
        return False
    await line_service.push_text_message(msg)
    logger.info(f"進行中リマインドLINE送信完了: {len(tasks)}件")
    return True


def _mark_sent(today: str) -> None:
    db = SessionLocal()
    try:
        cfg = db.query(AppSettings).first()
        if cfg:
            cfg.wip_reminder_last_sent = today
            db.commit()
    finally:
        db.close()


async def wip_reminder_scheduler() -> None:
    """5分ごとにチェックし、指定時刻を過ぎていてその日未送信なら送信する。"""
    await asyncio.sleep(35)

    if not settings.LINE_CHANNEL_ACCESS_TOKEN or not settings.LINE_USER_ID:
        logger.warning("LINE未設定のため、進行中リマインドスケジューラをスキップ")
        return

    logger.info("進行中リマインドスケジューラ開始（DB設定で有効/無効を制御）")

    while True:
        try:
            cfg = _get_cfg()
            if cfg and getattr(cfg, "wip_reminder_enabled", False):
                now = datetime.now(JST)
                today = now.strftime("%Y-%m-%d")
                hh = getattr(cfg, "wip_reminder_hour_jst", 9)
                mm = getattr(cfg, "wip_reminder_minute_jst", 5)
                target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if now >= target and getattr(cfg, "wip_reminder_last_sent", None) != today:
                    # 実際に送信できた時だけ「送信済み」にする。
                    # （対象0件で印を付けると、後から進行中タスクが出ても今日は二度と送らなくなるため）
                    sent = await send_wip_reminder()
                    if sent:
                        _mark_sent(today)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"進行中リマインドスケジューラエラー: {e}")
        await asyncio.sleep(300)
