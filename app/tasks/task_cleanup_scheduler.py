"""完了タスクの自動クリーンアップ。

「完了」のまま一定期間(既定14日)更新がないタスクを Notion アーカイブ（＝削除相当）する。
完了にした時点で last_edited_time が更新されるため、これを「完了してからの経過」の基準に使う。
（完了後にメモ追記などで編集した場合は、その時点から数え直しになる）

アーカイブは Notion のゴミ箱に入るだけなので、誤削除でも復元可能。
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.services import notion_service

logger = logging.getLogger(__name__)

# 完了タスクを保持する日数（これを過ぎたら自動アーカイブ）
DONE_RETENTION_DAYS = 14
# チェック間隔（6時間ごと）
CHECK_INTERVAL_SEC = 6 * 3600


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


async def collect_expired_done_tasks(days: int = DONE_RETENTION_DAYS) -> list[dict]:
    """アーカイブ対象（完了かつ最終更新から days 日経過）のタスクを返す。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    tasks = await notion_service.list_tasks(status="完了")
    expired = []
    for t in tasks:
        if t.get("status") != "完了":
            continue  # 念のため
        edited = _parse_iso(t.get("last_edited_time"))
        if edited and edited < cutoff:
            expired.append(t)
    return expired


async def cleanup_done_tasks(days: int = DONE_RETENTION_DAYS, dry_run: bool = False) -> dict:
    """完了から days 日経過したタスクをアーカイブする。

    返り値: {"targets": n, "archived": n, "names": [...]}
    """
    expired = await collect_expired_done_tasks(days)
    names = [t.get("name") or "（無題）" for t in expired]
    if dry_run:
        return {"targets": len(expired), "archived": 0, "names": names, "dry_run": True}

    archived = 0
    for t in expired:
        try:
            await notion_service.archive_task(t["id"])
            archived += 1
            logger.info(f"完了タスク自動削除: '{t.get('name')}' (last_edited={t.get('last_edited_time')})")
        except Exception as e:
            logger.error(f"完了タスク削除失敗: '{t.get('name')}': {e}")
    return {"targets": len(expired), "archived": archived, "names": names}


async def task_cleanup_scheduler() -> None:
    """6時間ごとに、完了から14日経過したタスクを自動アーカイブする。"""
    await asyncio.sleep(120)  # 起動直後は待機
    logger.info(f"完了タスク自動削除スケジューラ開始（{DONE_RETENTION_DAYS}日経過で削除）")
    while True:
        try:
            if notion_service.get_settings().NOTION_API_KEY:
                result = await cleanup_done_tasks()
                if result["archived"]:
                    logger.info(f"完了タスク自動削除: {result['archived']}件")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"完了タスク自動削除エラー: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SEC)
