"""毎週のタスク自動生成スケジューラ。

各テンプレートの指定曜日（以降、同週内）に Notion タスクを status=進行中 で作成する。
同じ週に二重作成しないよう last_created_week(ISO週) で管理する。
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models.recurring_task import RecurringTask
from app.services import notion_service

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))


def _iso_week(d: datetime) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


async def run_recurring_once() -> int:
    """期限が来ているテンプレートを生成する。作成した件数を返す。"""
    now = datetime.now(JST)
    today = now.date()
    cur_week = _iso_week(now)

    db = SessionLocal()
    try:
        templates = db.query(RecurringTask).filter(RecurringTask.enabled == True).all()  # noqa: E712
        due = [
            t for t in templates
            # 指定曜日 当日〜同週内で、今週まだ作成していないもの（取りこぼし救済）
            if today.weekday() >= t.weekday and t.last_created_week != cur_week
        ]
    finally:
        db.close()

    created = 0
    for t in due:
        # 今週の対象曜日の日付（例: 今週の水曜）を期日にする
        target_date = today - timedelta(days=(today.weekday() - t.weekday))
        try:
            await notion_service.create_task(
                name=t.name,
                project_id=t.project_id or None,
                status=t.create_status or "進行中",
                priority=t.priority or "中",
                due_date=target_date.strftime("%Y-%m-%d"),
            )
            # 成功したら今週分を記録
            db = SessionLocal()
            try:
                row = db.query(RecurringTask).filter(RecurringTask.id == t.id).first()
                if row:
                    row.last_created_week = cur_week
                    db.commit()
            finally:
                db.close()
            created += 1
            logger.info(f"毎週タスク作成: '{t.name}' (week={cur_week})")
        except Exception as e:
            logger.error(f"毎週タスク作成失敗: '{t.name}': {e}")

    return created


async def recurring_task_scheduler() -> None:
    """30分ごとに毎週タスクの生成条件をチェックする。"""
    await asyncio.sleep(30)
    logger.info("毎週タスクスケジューラ開始")
    while True:
        try:
            if not notion_service.get_settings().NOTION_API_KEY:
                await asyncio.sleep(1800)
                continue
            await run_recurring_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"毎週タスクスケジューラエラー: {e}")
        await asyncio.sleep(1800)
