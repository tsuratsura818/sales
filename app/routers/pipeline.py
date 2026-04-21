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


@router.get("/api/system/info")
async def system_info():
    """実行環境の情報(Claude CLI が利用可能か等)を返す。
    UI が「ローカル限定機能」を出し分けるために使う。
    """
    import os
    from app.services import local_claude
    is_render = bool(os.environ.get("RENDER"))
    return {
        "environment": "render" if is_render else "local",
        "local_claude_available": local_claude.is_available(),
    }


@router.post("/api/pipeline/runs/{run_id}/regenerate-proposals")
async def regenerate_run_proposals(
    run_id: int,
    ranks: str = Query("S,A", description="再生成対象のランク(カンマ区切り)"),
    db: Session = Depends(get_db),
):
    """既存 PipelineRun の結果に対して、ローカル Claude Code でバッチ提案文を再生成する。

    Render 本番では CLI 不在のため 503 を返す(クライアント側でローカル起動を促す)。
    """
    from app.services import local_claude
    from app.services.pipeline.runner import _enrich_with_proposals

    if not local_claude.is_available():
        raise HTTPException(
            status_code=503,
            detail="ローカル環境(Claude Code CLI)が必要です。" \
                   " ターミナルで `python scripts/regenerate_proposals.py --run-id %d` を実行してください。" % run_id,
        )

    run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Runが見つかりません")

    rank_list = [r.strip().upper() for r in ranks.split(",") if r.strip()]
    targets = (
        db.query(PipelineResult)
        .filter(
            PipelineResult.run_id == run_id,
            PipelineResult.rank.in_(rank_list),
        )
        .all()
    )
    if not targets:
        return {"regenerated": 0, "message": "対象ランクのリードがありません"}

    # personalized_subject/body をクリアして強制再生成させる
    for r in targets:
        r.personalized_subject = None
        r.personalized_body = None
    db.commit()

    await _enrich_with_proposals(targets, db)

    regenerated = sum(1 for r in targets if r.personalized_subject and r.personalized_body)
    return {
        "regenerated": regenerated,
        "total_candidates": len(targets),
        "ranks": rank_list,
    }


class CreateCampaignRequest(BaseModel):
    name: str
    sender_name: str = "西川"
    ranks: list[str] = ["S", "A"]
    list_name: str | None = None  # 既存list名 or 新規作成名
    send_start_time: str = "09:00"
    send_end_time: str = "18:00"
    ab_test: bool = False  # True なら A/B テストで2キャンペーン作成


@router.post("/api/pipeline/runs/{run_id}/create-campaign")
async def create_campaign_from_run(
    run_id: int,
    req: CreateCampaignRequest,
    db: Session = Depends(get_db),
):
    """ローカルClaude生成済みの PipelineResult から MailForgeキャンペーンを作成。

    フロー:
      1) S/A など指定ランクの PipelineResult を抽出 (personalized_subject/body 必須)
      2) Supabase contacts に upsert (idマップ取得)
      3) 必要なら contact_lists 作成
      4) campaigns INSERT (status='review')
      5) campaign_contacts INSERT (status='queued', subject/body 直書き)
      6) Render UI URL を返す
    """
    from app.services import mailforge_client as mf

    run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Runが見つかりません")

    rank_list = [r.strip().upper() for r in req.ranks if r.strip()]
    targets = (
        db.query(PipelineResult)
        .filter(
            PipelineResult.run_id == run_id,
            PipelineResult.rank.in_(rank_list),
            PipelineResult.email.isnot(None),
            PipelineResult.personalized_subject.isnot(None),
            PipelineResult.personalized_body.isnot(None),
        )
        .all()
    )
    if not targets:
        raise HTTPException(
            status_code=400,
            detail=f"対象なし: ranks={rank_list} かつ email/提案文が揃ったPipelineResultがありません。先にClaude再生成を実行してください。",
        )

    # 1) contact_lists (任意)
    list_id = ""
    if req.list_name:
        existing_lists = mf.get_contact_lists() or []
        match = next((l for l in existing_lists if l.get("name") == req.list_name), None)
        if match:
            list_id = match["id"]
        else:
            new_list = mf.create_contact_list(req.list_name, description=f"PipelineRun #{run_id}")
            list_id = (new_list or {}).get("id", "")

    # 2) contacts upsert
    contacts_payload = []
    for r in targets:
        contacts_payload.append({
            "email": r.email,
            "company_name": r.company or "",
            "industry": r.industry or "",
            "website_url": r.website or "",
            "notes": (r.platform or "") + (" / " + (r.ec_status or "") if r.ec_status else ""),
            "custom_fields": {
                "category": r.category or "",
                "rank": r.rank or "",
                "score": str(r.score or 0),
                "source": r.source or "",
            },
        })
    upsert_result = mf.upsert_contacts(contacts_payload, list_id=list_id)
    email_to_id = upsert_result.get("email_to_id", {})
    if not email_to_id:
        raise HTTPException(status_code=500, detail=f"contacts upsert 失敗: {upsert_result}")

    base_campaign_data = {
        "status": "review",
        "sender_name": req.sender_name,
        "send_start_time": req.send_start_time,
        "send_end_time": req.send_end_time,
        "send_days": [1, 2, 3, 4, 5],
        "min_interval_sec": 120,
        "max_interval_sec": 300,
        "total_contacts": 0,
        "subject_template": "(個別生成済み)",
        "body_template": "(個別生成済み)",
    }
    if list_id:
        base_campaign_data["list_id"] = list_id

    if req.ab_test:
        # A/B テスト: 2キャンペーン作成、contacts 50/50 分割
        # 既存件名を subject_a とし、別の切り口の subject_b を新規生成
        from app.services import proposal_service, local_claude
        if not local_claude.is_available():
            raise HTTPException(
                status_code=503,
                detail="A/Bテストには Claude CLI が必要です(ローカル実行してください)",
            )

        ab_targets = [
            {
                "url": r.website or "",
                "company": r.company or "",
                "industry": r.industry or "",
                "category": r.category or "B",
                "prefecture": r.location or "",
                "analysis": json.loads(r.site_analysis) if r.site_analysis else {},
            }
            for r in targets
        ]
        ab_props = await proposal_service.generate_batch_proposals_ab(ab_targets)

        # hash で安定した 50/50 分割
        group_a_items, group_b_items = [], []
        import hashlib
        for r, ab in zip(targets, ab_props):
            cid = email_to_id.get(r.email.lower())
            if not cid or not ab.get("subject_a") or not ab.get("body"):
                continue
            bucket = int(hashlib.md5(cid.encode()).hexdigest(), 16) % 2
            body_txt = ab["body"]
            if bucket == 0:
                group_a_items.append({
                    "contact_id": cid,
                    "personalized_subject": ab["subject_a"],
                    "personalized_body": body_txt,
                })
            else:
                group_b_items.append({
                    "contact_id": cid,
                    "personalized_subject": ab.get("subject_b") or ab["subject_a"],
                    "personalized_body": body_txt,
                })

        campaign_a = mf.create_campaign({**base_campaign_data, "name": f"{req.name} [A]"})
        campaign_b = mf.create_campaign({**base_campaign_data, "name": f"{req.name} [B]"})
        if not (campaign_a and campaign_b and campaign_a.get("id") and campaign_b.get("id")):
            raise HTTPException(status_code=500, detail=f"A/B campaign作成失敗")
        cid_a, cid_b = campaign_a["id"], campaign_b["id"]

        r_a = mf.create_campaign_contacts(cid_a, group_a_items)
        r_b = mf.create_campaign_contacts(cid_b, group_b_items)
        n_a, n_b = r_a.get("inserted", 0), r_b.get("inserted", 0)
        if n_a > 0: mf.update_campaign(cid_a, {"total_contacts": n_a})
        if n_b > 0: mf.update_campaign(cid_b, {"total_contacts": n_b})

        return {
            "success": True,
            "ab_test": True,
            "campaign_a": {"id": cid_a, "name": f"{req.name} [A]", "contacts": n_a,
                            "url": f"https://sales-6g78.onrender.com/mail/campaigns/{cid_a}"},
            "campaign_b": {"id": cid_b, "name": f"{req.name} [B]", "contacts": n_b,
                            "url": f"https://sales-6g78.onrender.com/mail/campaigns/{cid_b}"},
            "contacts_upserted": upsert_result.get("inserted", 0) + upsert_result.get("skipped", 0),
        }

    # --- 通常モード(1キャンペーン) ---
    campaign = mf.create_campaign({**base_campaign_data, "name": req.name})
    if not campaign or not campaign.get("id"):
        raise HTTPException(status_code=500, detail=f"campaign作成失敗: {campaign}")
    campaign_id = campaign["id"]

    cc_items = []
    for r in targets:
        cid = email_to_id.get(r.email.lower())
        if not cid:
            continue
        cc_items.append({
            "contact_id": cid,
            "personalized_subject": r.personalized_subject,
            "personalized_body": r.personalized_body,
        })
    cc_result = mf.create_campaign_contacts(campaign_id, cc_items)
    actual_count = cc_result.get("inserted", 0)
    if actual_count > 0:
        mf.update_campaign(campaign_id, {"total_contacts": actual_count})

    return {
        "success": True,
        "ab_test": False,
        "campaign_id": campaign_id,
        "campaign_name": req.name,
        "contacts_upserted": upsert_result.get("inserted", 0) + upsert_result.get("skipped", 0),
        "campaign_contacts_inserted": actual_count,
        "render_url": f"https://sales-6g78.onrender.com/mail/campaigns/{campaign_id}",
    }


@router.post("/api/pipeline/results/{result_id}/promote")
async def promote_result_to_lead(result_id: int, db: Session = Depends(get_db)):
    """単一の PipelineResult を Lead テーブルに昇格させる"""
    from app.services import promotion_service
    result = db.query(PipelineResult).filter(PipelineResult.id == result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="結果が見つかりません")
    lead = promotion_service.promote_to_lead(result, db)
    if not lead:
        return {"promoted": False, "message": "既に昇格済みです"}
    return {"promoted": True, "lead_id": lead.id, "url": f"/leads/{lead.id}"}


@router.post("/api/pipeline/runs/{run_id}/promote")
async def promote_run_to_leads(
    run_id: int,
    ranks: str = Query("S,A", description="カンマ区切りの対象ランク"),
    db: Session = Depends(get_db),
):
    """指定 PipelineRun の対象ランクのリードをまとめて昇格"""
    from app.services import promotion_service
    rank_list = tuple(r.strip().upper() for r in ranks.split(",") if r.strip())
    return promotion_service.promote_run(run_id, db, ranks=rank_list)


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
