"""リスト収集パイプライン ルーター

POST /api/pipeline/start - パイプライン実行開始
GET  /api/pipeline/status/{run_id} - 実行状況
GET  /api/pipeline/runs - 実行履歴
GET  /api/pipeline/results/{run_id} - 収集結果
GET  /api/pipeline/keywords - キーワード一覧
POST /api/pipeline/keywords - キーワード追加
PATCH /api/pipeline/keywords/{id} - キーワード更新
DELETE /api/pipeline/keywords/{id} - キーワード削除
GET  /pipeline - パイプラインUI
GET  /pipeline/keywords - キーワード管理UI
"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.pipeline import PipelineRun, PipelineResult
from app.models.pipeline_keyword import PipelineKeyword
from app.services.pipeline.runner import run_pipeline
from app.services.pipeline.config import SEARCH_KEYWORDS

router = APIRouter(tags=["pipeline"])

# 実行中タスクの追跡
_running_tasks: dict[int, asyncio.Task] = {}


def _get_templates():
    from main import templates
    return templates


class PipelineStartRequest(BaseModel):
    sources: list[str] = ["yahoo", "rakuten", "google", "duckduckgo"]
    skip_mx: bool = True
    # モード: ec (関西EC特化) / category (全国カテゴリA-D) / both
    mode: str = "ec"
    # カテゴリモード設定
    categories: list[str] | None = None              # ["A","B","C","D"]
    prefectures: list[str] | None = None              # 例: ["東京","大阪"] None=主要10都市
    max_queries_per_category: int | None = 50
    max_urls_per_category: int | None = 150
    generate_proposals: bool = True                   # 個別提案文生成を有効化


@router.get("/pipeline", response_class=HTMLResponse)
async def pipeline_page(request: Request):
    return _get_templates().TemplateResponse(request, "pipeline.html", {})


@router.post("/api/pipeline/start")
async def start_pipeline(data: PipelineStartRequest, db: Session = Depends(get_db)):
    """パイプライン実行（リクエスト内で直接実行 — Render無料プラン対応）"""
    # 既に実行中のものがないかチェック
    running = db.query(PipelineRun).filter(PipelineRun.status == "running").first()
    if running:
        return {"error": "パイプラインが既に実行中です", "run_id": running.id}

    # カテゴリモード時は sources に "category" を自動追加
    effective_sources = list(data.sources)
    if data.mode in ("category", "both") and "category" not in effective_sources:
        effective_sources.append("category")

    category_config = {
        "categories": data.categories or ["A", "B", "C", "D"],
        "prefectures": data.prefectures,
        "max_queries_per_category": data.max_queries_per_category or 50,
        "max_urls_per_category": data.max_urls_per_category or 150,
        "generate_proposals": data.generate_proposals,
    } if data.mode in ("category", "both") else None

    run = PipelineRun(
        sources=json.dumps(effective_sources),
        keywords_count=len(SEARCH_KEYWORDS),
        skip_mx=1 if data.skip_mx else 0,
        status="pending",
        mode=data.mode,
        category_config=json.dumps(category_config, ensure_ascii=False) if category_config else None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # リクエスト内で直接実行（バックグラウンドタスクはRender無料プランで不安定）
    await run_pipeline(run.id)

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


# ========================================
# キーワード管理
# ========================================

class KeywordCreate(BaseModel):
    keyword: str
    industry: str
    source: str = "all"
    note: str | None = None


class KeywordUpdate(BaseModel):
    keyword: str | None = None
    industry: str | None = None
    source: str | None = None
    enabled: int | None = None
    note: str | None = None


@router.get("/pipeline/keywords", response_class=HTMLResponse)
async def keywords_page(request: Request):
    return _get_templates().TemplateResponse(request, "pipeline_keywords.html", {})


@router.get("/api/pipeline/keywords")
async def list_keywords(
    enabled_only: bool = False,
    db: Session = Depends(get_db),
):
    """キーワード一覧"""
    try:
        query = db.query(PipelineKeyword).order_by(PipelineKeyword.industry, PipelineKeyword.id)
        if enabled_only:
            query = query.filter(PipelineKeyword.enabled == 1)
        keywords = query.all()
    except Exception as e:
        # テーブルが存在しない場合の初回対応
        import logging
        logging.getLogger(__name__).error(f"keywords query error: {e}")
        return {"keywords": [], "total": 0, "enabled_count": 0, "industries": {}, "error": str(e)[:200]}

    industries: dict[str, int] = {}
    for kw in keywords:
        industries[kw.industry] = industries.get(kw.industry, 0) + 1

    return {
        "keywords": [
            {
                "id": kw.id,
                "keyword": kw.keyword,
                "industry": kw.industry,
                "source": kw.source,
                "enabled": kw.enabled,
                "note": kw.note,
            }
            for kw in keywords
        ],
        "total": len(keywords),
        "enabled_count": sum(1 for kw in keywords if kw.enabled),
        "industries": industries,
    }


@router.post("/api/pipeline/keywords")
async def create_keyword(data: KeywordCreate, db: Session = Depends(get_db)):
    """キーワード追加"""
    if not data.keyword.strip() or not data.industry.strip():
        raise HTTPException(status_code=400, detail="キーワードと業種は必須です")

    kw = PipelineKeyword(
        keyword=data.keyword.strip(),
        industry=data.industry.strip(),
        source=data.source,
        note=data.note,
        enabled=1,
    )
    db.add(kw)
    db.commit()
    db.refresh(kw)
    return {"success": True, "id": kw.id}


@router.post("/api/pipeline/keywords/bulk")
async def bulk_create_keywords(keywords: list[KeywordCreate], db: Session = Depends(get_db)):
    """キーワード一括追加"""
    added = 0
    for data in keywords:
        if not data.keyword.strip() or not data.industry.strip():
            continue
        kw = PipelineKeyword(
            keyword=data.keyword.strip(),
            industry=data.industry.strip(),
            source=data.source,
            note=data.note,
            enabled=1,
        )
        db.add(kw)
        added += 1
    db.commit()
    return {"success": True, "added": added}


@router.patch("/api/pipeline/keywords/{keyword_id}")
async def update_keyword(keyword_id: int, data: KeywordUpdate, db: Session = Depends(get_db)):
    """キーワード更新"""
    kw = db.query(PipelineKeyword).filter(PipelineKeyword.id == keyword_id).first()
    if not kw:
        raise HTTPException(status_code=404, detail="キーワードが見つかりません")

    if data.keyword is not None:
        kw.keyword = data.keyword.strip()
    if data.industry is not None:
        kw.industry = data.industry.strip()
    if data.source is not None:
        kw.source = data.source
    if data.enabled is not None:
        kw.enabled = data.enabled
    if data.note is not None:
        kw.note = data.note
    db.commit()
    return {"success": True}


@router.delete("/api/pipeline/keywords/{keyword_id}")
async def delete_keyword(keyword_id: int, db: Session = Depends(get_db)):
    """キーワード削除"""
    kw = db.query(PipelineKeyword).filter(PipelineKeyword.id == keyword_id).first()
    if not kw:
        raise HTTPException(status_code=404, detail="キーワードが見つかりません")
    db.delete(kw)
    db.commit()
    return {"success": True}


@router.post("/api/pipeline/test")
async def test_pipeline(db: Session = Depends(get_db)):
    """デバッグ: Yahoo!のみ、キーワード3件で即テスト（同期実行）"""
    import logging
    log = logging.getLogger("pipeline.test")

    try:
        from app.services.pipeline.yahoo_collector import collect, CollectedLead
        from app.services.pipeline.config import SEARCH_KEYWORDS

        test_kw = SEARCH_KEYWORDS[:3]
        seen: set[str] = set()
        log.info(f"テスト実行: {len(test_kw)}キーワード")

        leads = await collect(seen, keywords=test_kw)
        return {
            "success": True,
            "found": len(leads),
            "keywords_used": len(test_kw),
            "leads": [{"email": l.email, "company": l.company, "industry": l.industry} for l in leads[:5]],
        }
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()[-500:]}


@router.post("/api/pipeline/cancel/{run_id}")
async def cancel_pipeline(run_id: int, db: Session = Depends(get_db)):
    """stuckしたパイプラインをキャンセル"""
    run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="実行が見つかりません")
    if run.status == "running":
        run.status = "failed"
        run.error_message = "手動キャンセル"
        run.progress_message = "キャンセル済み"
        from datetime import datetime
        run.completed_at = datetime.now()
        db.commit()
    return {"success": True}


@router.patch("/api/pipeline/keywords/toggle-all")
async def toggle_all_keywords(enabled: int = Query(...), db: Session = Depends(get_db)):
    """全キーワードの有効/無効を一括切り替え"""
    db.query(PipelineKeyword).update({"enabled": enabled})
    db.commit()
    return {"success": True}
