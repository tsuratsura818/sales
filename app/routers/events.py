import asyncio
import json
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.tasks import progress_store

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events/{job_id}")
async def sse_progress(job_id: int):
    """SSEストリームで進捗をリアルタイム配信する"""

    async def event_generator():
        # まず現在の状態を送信
        current = progress_store.get(job_id)
        if current:
            yield {"data": json.dumps(current, ensure_ascii=False)}

            if current.get("status") == "completed":
                return

        # 購読キューから更新を受け取る
        q = progress_store.subscribe(job_id)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30)
                    yield {"data": json.dumps(data, ensure_ascii=False)}
                    if data.get("status") == "completed":
                        break
                except asyncio.TimeoutError:
                    # キープアライブ
                    yield {"data": json.dumps({"ping": True})}
        finally:
            progress_store.unsubscribe(job_id, q)

    return EventSourceResponse(event_generator())
