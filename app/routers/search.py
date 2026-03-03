import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.search_job import SearchJob
from app.schemas.search_job import SearchRequest, SearchJobResponse
from app.tasks import task_queue

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search", response_model=SearchJobResponse)
async def create_search(request: SearchRequest, db: Session = Depends(get_db)):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="クエリを入力してください")

    job = SearchJob(
        query=request.query,
        industry=request.industry,
        region=request.region,
        num_results=request.num_results,
        status="pending",
        filter_http_only=request.filter_http_only,
        filter_no_mobile=request.filter_no_mobile,
        filter_cms_list=json.dumps(request.filter_cms_list, ensure_ascii=False) if request.filter_cms_list else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task_queue.enqueue(job.id)

    return SearchJobResponse(
        job_id=job.id,
        status="pending",
        message=f"ジョブ #{job.id} を作成しました。分析を開始します。",
    )


@router.get("/search/{job_id}")
async def get_job_status(job_id: int, db: Session = Depends(get_db)):
    job = db.query(SearchJob).filter(SearchJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {
        "job_id": job.id,
        "query": job.query,
        "status": job.status,
        "total_urls": job.total_urls,
        "analyzed_count": job.analyzed_count,
        "serpapi_calls_used": job.serpapi_calls_used,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }
