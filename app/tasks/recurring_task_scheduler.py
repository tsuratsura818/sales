"""定期タスク自動生成スケジューラ（毎週/毎月）。

- 毎週(weekly): 指定曜日（以降、同週内）に Notion タスクを作成。last_created_week(ISO週)で重複防止。
- 毎月(monthly): 指定日（0=末日）以降、同月内に作成。last_created_month("YYYY-MM")で重複防止。
作成は status=進行中 で行い、完了するまで残る。
"""

import asyncio
import calendar
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


def _monthly_target_day(today, day_of_month: int) -> int:
    """月内の生成対象日。0=末日。指定日がその月に無ければ末日に丸める。"""
    last_dom = calendar.monthrange(today.year, today.month)[1]
    if not day_of_month or day_of_month <= 0:
        return last_dom
    return min(day_of_month, last_dom)


async def run_recurring_once() -> int:
    """期限が来ているテンプレートを生成する（毎週/毎月）。作成した件数を返す。"""
    now = datetime.now(JST)
    today = now.date()
    cur_week = _iso_week(now)
    cur_month = today.strftime("%Y-%m")

    db = SessionLocal()
    try:
        templates = db.query(RecurringTask).filter(RecurringTask.enabled == True).all()  # noqa: E712
        weekly_cands = []
        monthly_cands = []
        for t in templates:
            freq = getattr(t, "freq", "weekly") or "weekly"
            base = {"id": t.id, "name": t.name, "project_id": t.project_id,
                    "create_status": t.create_status, "priority": t.priority}
            if freq == "monthly":
                target_day = _monthly_target_day(today, getattr(t, "day_of_month", 0) or 0)
                # 対象日 当日〜月内で、今月まだ作成していないもの（取りこぼし救済）
                if today.day >= target_day and getattr(t, "last_created_month", None) != cur_month:
                    monthly_cands.append({**base, "target_day": target_day})
            else:
                # 指定曜日 当日〜同週内で、今週まだ作成していないもの
                if today.weekday() >= t.weekday and t.last_created_week != cur_week:
                    weekly_cands.append({**base, "weekday": t.weekday})
    finally:
        db.close()

    created = 0

    # ---- 毎週 ----
    for c in weekly_cands:
        if not _claim(c["id"], "last_created_week", cur_week):
            continue  # 既に他が今週分を確保済み
        target_date = today - timedelta(days=(today.weekday() - c["weekday"]))
        if await _create(c, target_date):
            created += 1
            logger.info(f"毎週タスク作成: '{c['name']}' (week={cur_week})")
        else:
            _release(c["id"], "last_created_week", cur_week)

    # ---- 毎月 ----
    for c in monthly_cands:
        if not _claim(c["id"], "last_created_month", cur_month):
            continue
        target_date = today.replace(day=c["target_day"])
        if await _create(c, target_date):
            created += 1
            logger.info(f"毎月タスク作成: '{c['name']}' (month={cur_month}, day={c['target_day']})")
        else:
            _release(c["id"], "last_created_month", cur_month)

    return created


def _claim(rid: int, col: str, value: str) -> bool:
    """重複作成防止: 指定カラムを原子的に確保（再起動/多重起動でも1回だけ通る）。"""
    column = getattr(RecurringTask, col)
    db = SessionLocal()
    try:
        result = db.execute(
            update(RecurringTask)
            .where(RecurringTask.id == rid, (column.is_(None)) | (column != value))
            .values({col: value})
        )
        db.commit()
        return result.rowcount == 1
    finally:
        db.close()


def _release(rid: int, col: str, value: str) -> None:
    """作成失敗時に確保を戻して次回リトライ可能にする。"""
    column = getattr(RecurringTask, col)
    db = SessionLocal()
    try:
        db.execute(
            update(RecurringTask).where(RecurringTask.id == rid, column == value).values({col: None})
        )
        db.commit()
    finally:
        db.close()


async def _create(c: dict, target_date) -> bool:
    try:
        await notion_service.create_task(
            name=c["name"],
            project_id=c["project_id"] or None,
            status=c["create_status"] or "進行中",
            priority=c["priority"] or "中",
            due_date=target_date.strftime("%Y-%m-%d"),
        )
        return True
    except Exception as e:
        logger.error(f"定期タスク作成失敗（確保を戻し）: '{c['name']}': {e}")
        return False


async def recurring_task_scheduler() -> None:
    """30分ごとに定期タスク（毎週/毎月）の生成条件をチェックする。"""
    await asyncio.sleep(30)
    logger.info("定期タスクスケジューラ開始")
    while True:
        try:
            if not notion_service.get_settings().NOTION_API_KEY:
                await asyncio.sleep(1800)
                continue
            await run_recurring_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"定期タスクスケジューラエラー: {e}")
        await asyncio.sleep(1800)
