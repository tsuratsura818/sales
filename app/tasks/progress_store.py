import asyncio
from typing import Any

# job_id -> 進捗情報
_progress: dict[int, dict[str, Any]] = {}

# job_id -> SSE購読キューのリスト
_listeners: dict[int, list[asyncio.Queue]] = {}


def init_job(job_id: int, total: int) -> None:
    _progress[job_id] = {
        "job_id": job_id,
        "total": total,
        "completed": 0,
        "status": "running",
        "current_url": "",
        "errors": 0,
        "eta_seconds": 0,
        "avg_seconds": 0,
    }
    _listeners.setdefault(job_id, [])  # 既存の購読者を保持


async def update(job_id: int, **kwargs) -> None:
    if job_id not in _progress:
        return
    _progress[job_id].update(kwargs)
    data = _progress[job_id].copy()
    for q in list(_listeners.get(job_id, [])):
        await q.put(data)


def get(job_id: int) -> dict | None:
    return _progress.get(job_id)


def subscribe(job_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _listeners.setdefault(job_id, []).append(q)
    return q


def unsubscribe(job_id: int, q: asyncio.Queue) -> None:
    listeners = _listeners.get(job_id, [])
    if q in listeners:
        listeners.remove(q)
