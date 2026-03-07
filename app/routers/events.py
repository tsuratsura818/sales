import asyncio
import json
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.tasks import progress_store
from app.database import SessionLocal
from app.models.search_job import SearchJob

router = APIRouter(prefix="/api", tags=["events"])


def _get_job_from_db(job_id: int) -> dict:
    """progress_storeにデータがない場合、DBから取得"""
    db = SessionLocal()
    try:
        job = db.query(SearchJob).filter(SearchJob.id == job_id).first()
        if not job:
            return {"status": "unknown", "job_id": job_id}
        return {
            "job_id": job_id,
            "total": job.total_urls or job.num_results or 0,
            "completed": job.analyzed_count or 0,
            "status": job.status or "running",
            "current_url": "",
            "errors": 0,
            "eta_seconds": 0,
            "avg_seconds": 0,
        }
    finally:
        db.close()


@router.get("/events/{job_id}")
async def sse_progress(job_id: int):
    """SSEストリームで進捗をリアルタイム配信する"""

    async def event_generator():
        current = progress_store.get(job_id)
        if not current:
            current = _get_job_from_db(job_id)
        if current:
            yield {"data": json.dumps(current, ensure_ascii=False)}
            if current.get("status") in ("completed", "failed"):
                return

        q = progress_store.subscribe(job_id)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=10)
                    yield {"data": json.dumps(data, ensure_ascii=False)}
                    if data.get("status") in ("completed", "failed"):
                        break
                except asyncio.TimeoutError:
                    yield {"data": json.dumps({"ping": True})}
        finally:
            progress_store.unsubscribe(job_id, q)

    return EventSourceResponse(event_generator())


@router.get("/progress/{job_id}")
async def get_progress(job_id: int):
    """SSEフォールバック用: ポーリングで進捗を返す"""
    current = progress_store.get(job_id)
    if current:
        return current
    return _get_job_from_db(job_id)
