"""リスト収集パイプライン ルーター

POST /api/pipeline/start - パイプライン実行開始
GET  /api/pipeline/status/{run_id} - 実行状況
GET  /api/pipeline/runs - 実行履歴
GET  /api/pipeline/results/{run_id} - 収集結果
GET  /pipeline - パイプラインUI
"""
import asyncio
import json

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.pipeline import PipelineRun, PipelineResult
from app.services.pipeline.runner import run_pipeline
from app.services.pipeline.config import SEARCH_KEYWORDS

router = APIRouter(tags=["pipeline"])

# 実行中タスクの追跡
_running_tasks: dict[int, asyncio.Task] = {}


def _get_templates():
    from main import templates
    return templates


class PipelineStartRequest(BaseModel):
    sources: list[str] = ["yahoo", "rakuten", "google"]
    skip_mx: bool = True


@router.get("/pipeline", response_class=HTMLResponse)
async def pipeline_page(request: Request):
    return _get_templates().TemplateResponse(request, "pipeline.html", {})


@router.post("/api/pipeline/start")
async def start_pipeline(data: PipelineStartRequest, db: Session = Depends(get_db)):
    """パイプライン実行を開始（バックグラウンド）"""
    # 既に実行中のものがないかチェック
    running = db.query(PipelineRun).filter(PipelineRun.status == "running").first()
    if running:
        return {"error": "パイプラインが既に実行中です", "run_id": running.id}

    run = PipelineRun(
        sources=json.dumps(data.sources),
        keywords_count=len(SEARCH_KEYWORDS),
        skip_mx=1 if data.skip_mx else 0,
        status="pending",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # バックグラウンドタスクとして実行
    task = asyncio.create_task(run_pipeline(run.id))
    _running_tasks[run.id] = task

    return {"success": True, "run_id": run.id}


@router.get("/api/pipeline/status/{run_id}")
async def pipeline_status(run_id: int, db: Session = Depends(get_db)):
    """パイプライン実行状況"""
    run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
    if not run:
        return {"error": "実行が見つかりません"}

    # ランク別集計
    rank_counts = {}
    if run.status == "completed":
        results = db.query(PipelineResult).filter(PipelineResult.run_id == run_id).all()
        for r in results:
            rank = r.rank or "?"
            rank_counts[rank] = rank_counts.get(rank, 0) + 1

    return {
        "id": run.id,
        "status": run.status,
        "progress_pct": run.progress_pct,
        "progress_message": run.progress_message,
        "total_found": run.total_found,
        "total_imported": run.total_imported,
        "duration_sec": run.duration_sec,
        "error_message": run.error_message,
        "source_breakdown": json.loads(run.source_breakdown) if run.source_breakdown else {},
        "rank_counts": rank_counts,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.get("/api/pipeline/runs")
async def pipeline_runs(db: Session = Depends(get_db)):
    """実行履歴一覧"""
    runs = db.query(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(20).all()
    return {
        "runs": [
            {
                "id": r.id,
                "status": r.status,
                "sources": json.loads(r.sources) if r.sources else [],
                "total_found": r.total_found,
                "total_imported": r.total_imported,
                "duration_sec": r.duration_sec,
                "source_breakdown": json.loads(r.source_breakdown) if r.source_breakdown else {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in runs
        ]
    }


@router.get("/api/pipeline/results/{run_id}")
async def pipeline_results(
    run_id: int,
    rank: str | None = None,
    source: str | None = None,
    sort: str = "score",
    db: Session = Depends(get_db),
):
    """収集結果一覧（フィルタ・ソート対応）"""
    query = db.query(PipelineResult).filter(PipelineResult.run_id == run_id)
    if rank:
        query = query.filter(PipelineResult.rank == rank)
    if source:
        query = query.filter(PipelineResult.source == source)

    if sort == "score":
        query = query.order_by(desc(PipelineResult.score))
    elif sort == "company":
        query = query.order_by(PipelineResult.company)
    else:
        query = query.order_by(desc(PipelineResult.created_at))

    results = query.all()

    return {
        "results": [
            {
                "id": r.id,
                "email": r.email,
                "company": r.company,
                "industry": r.industry,
                "location": r.location,
                "website": r.website,
                "platform": r.platform,
                "ec_status": r.ec_status,
                "proposal": r.proposal,
                "source": r.source,
                "score": r.score,
                "rank": r.rank,
                "imported_to_mailforge": r.imported_to_mailforge,
            }
            for r in results
        ],
        "total": len(results),
    }


@router.get("/api/pipeline/results/{run_id}/csv")
async def export_csv(run_id: int, db: Session = Depends(get_db)):
    """結果CSVエクスポート"""
    results = db.query(PipelineResult).filter(
        PipelineResult.run_id == run_id
    ).order_by(desc(PipelineResult.score)).all()

    import csv
    import io

    output = io.StringIO()
    output.write('\ufeff')  # BOM
    writer = csv.writer(output)
    writer.writerow(["ランク", "スコア", "会社名", "業種", "所在地", "メール", "サイトURL", "EC状況", "提案切り口", "プラットフォーム", "ソース"])
    for r in results:
        writer.writerow([r.rank, r.score, r.company, r.industry, r.location, r.email, r.website, r.ec_status, r.proposal, r.platform, r.source])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=pipeline_results_{run_id}.csv"},
    )
