"""毎週のタスク自動生成スケジューラ。

各テンプレートの指定曜日（以降、同週内）に Notion タスクを status=進行中 で作成する。
同じ週に二重作成しないよう last_created_week(ISO週) で管理する。
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

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
        # 指定曜日 当日〜同週内で、今週まだ作成していないもの（取りこぼし救済）
        candidates = [
            {"id": t.id, "name": t.name, "weekday": t.weekday,
             "project_id": t.project_id, "create_status": t.create_status, "priority": t.priority}
            for t in templates
            if today.weekday() >= t.weekday and t.last_created_week != cur_week
        ]
    finally:
        db.close()

    created = 0
    for c in candidates:
        # 二重作成防止: 先に「今週分」を原子的に確保（他プロセス/再起動と競合しても1回だけ通る）
        db = SessionLocal()
        try:
            result = db.execute(
                update(RecurringTask)
                .where(
                    RecurringTask.id == c["id"],
                    (RecurringTask.last_created_week.is_(None))
                    | (RecurringTask.last_created_week != cur_week),
                )
                .values(last_created_week=cur_week)
            )
            db.commit()
            claimed = result.rowcount == 1
        finally:
            db.close()
        if not claimed:
            continue  # 既に他が今週分を確保済み

        target_date = today - timedelta(days=(today.weekday() - c["weekday"]))
        try:
            await notion_service.create_task(
                name=c["name"],
                project_id=c["project_id"] or None,
                status=c["create_status"] or "進行中",
                priority=c["priority"] or "中",
                due_date=target_date.strftime("%Y-%m-%d"),
            )
            created += 1
            logger.info(f"毎週タスク作成: '{c['name']}' (week={cur_week})")
        except Exception as e:
            # 作成失敗時は確保を戻して次回リトライできるようにする
            db = SessionLocal()
            try:
                db.execute(
                    update(RecurringTask)
                    .where(RecurringTask.id == c["id"], RecurringTask.last_created_week == cur_week)
                    .values(last_created_week=None)
                )
                db.commit()
            finally:
                db.close()
            logger.error(f"毎週タスク作成失敗（確保を戻し）: '{c['name']}': {e}")

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
