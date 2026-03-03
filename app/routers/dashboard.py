import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.search_job import SearchJob
from app.models.lead import Lead
from app.models.email_log import EmailLog
from app.models.follow_up import FollowUpStep
from app.models.competitor import CompetitorAnalysis
from app.services.screenshot_service import get_screenshot_urls
from app.services.portfolio_service import get_portfolios_for_lead, SERVICE_TYPES as PORTFOLIO_SERVICE_TYPES

router = APIRouter(tags=["dashboard"])

# SerpAPIコスト: 有料プラン $50/5000件 = $0.01/call = 約1.5円/call
SERPAPI_COST_PER_CALL_JPY = 1.5
# Claude Opus メール生成: 入力500tok + 出力300tok ≈ $0.030 ≈ 4.5円/件
CLAUDE_COST_PER_EMAIL_JPY = 4.5


def _get_templates():
    from main import templates
    return templates


def _calc_cost(job: SearchJob) -> dict:
    serpapi_cost = round((job.serpapi_calls_used or 0) * SERPAPI_COST_PER_CALL_JPY)
    return {
        "serpapi_calls": job.serpapi_calls_used or 0,
        "serpapi_cost_jpy": serpapi_cost,
        "claude_cost_per_email_jpy": CLAUDE_COST_PER_EMAIL_JPY,
    }


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return _get_templates().TemplateResponse("dashboard.html", {"request": request})


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    jobs = db.query(SearchJob).order_by(desc(SearchJob.created_at)).limit(5).all()
    jobs_with_cost = [{"job": j, "cost": _calc_cost(j)} for j in jobs]
    return _get_templates().TemplateResponse("index.html", {
        "request": request,
        "recent_jobs": jobs,
        "jobs_with_cost": jobs_with_cost,
    })


@router.get("/leads", response_class=HTMLResponse)
async def leads_page(request: Request, job_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Lead)
    job = None
    cost = None
    active_cms_list = []

    if job_id:
        query = query.filter(Lead.search_job_id == job_id)
        job = db.query(SearchJob).filter(SearchJob.id == job_id).first()
        if job:
            cost = _calc_cost(job)
            if job.filter_cms_list:
                try:
                    active_cms_list = json.loads(job.filter_cms_list)
                except Exception:
                    active_cms_list = []

    leads = query.filter(Lead.status != "excluded").order_by(desc(Lead.score)).all()

    for lead in leads:
        if lead.score_breakdown and isinstance(lead.score_breakdown, str):
            try:
                lead._breakdown = json.loads(lead.score_breakdown)
            except Exception:
                lead._breakdown = {}
        else:
            lead._breakdown = {}

    return _get_templates().TemplateResponse("leads.html", {
        "request": request,
        "leads": leads,
        "job": job,
        "job_id": job_id,
        "cost": cost,
        "active_cms_list": active_cms_list,
    })


@router.get("/leads/{lead_id}", response_class=HTMLResponse)
async def lead_detail_page(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return HTMLResponse("<h1>リードが見つかりません</h1>", status_code=404)

    breakdown = {}
    if lead.score_breakdown:
        try:
            breakdown = json.loads(lead.score_breakdown)
        except Exception:
            pass

    screenshots = get_screenshot_urls(lead.id)

    follow_up_steps = (
        db.query(FollowUpStep)
        .filter(FollowUpStep.lead_id == lead_id)
        .order_by(FollowUpStep.step_number)
        .all()
    )

    # 競合分析結果（最新）
    competitor_analysis = (
        db.query(CompetitorAnalysis)
        .filter(CompetitorAnalysis.lead_id == lead_id)
        .order_by(desc(CompetitorAnalysis.created_at))
        .first()
    )
    comp_summary = {}
    if competitor_analysis and competitor_analysis.comparison_summary:
        try:
            comp_summary = json.loads(competitor_analysis.comparison_summary)
        except Exception:
            pass

    # Phase 7: ポートフォリオ
    matched_portfolios = get_portfolios_for_lead(db, lead)

    return _get_templates().TemplateResponse("lead_detail.html", {
        "request": request,
        "lead": lead,
        "breakdown": breakdown,
        "screenshots": screenshots,
        "follow_up_steps": follow_up_steps,
        "competitor_analysis": competitor_analysis,
        "comp_summary": comp_summary,
        "matched_portfolios": matched_portfolios,
        "portfolio_service_types": PORTFOLIO_SERVICE_TYPES,
    })


@router.delete("/api/jobs/{job_id}")
async def delete_job(job_id: int, db: Session = Depends(get_db)):
    """ジョブと配下のリード・メールログを全削除"""
    job = db.query(SearchJob).filter(SearchJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")

    # 配下のリードIDを取得してフォローアップ・メールログも削除
    lead_ids = [lid for (lid,) in db.query(Lead.id).filter(Lead.search_job_id == job_id).all()]
    if lead_ids:
        db.query(CompetitorAnalysis).filter(CompetitorAnalysis.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        db.query(FollowUpStep).filter(FollowUpStep.lead_id.in_(lead_ids)).delete(synchronize_session=False)
        db.query(EmailLog).filter(EmailLog.lead_id.in_(lead_ids)).delete(synchronize_session=False)
    db.query(Lead).filter(Lead.search_job_id == job_id).delete(synchronize_session=False)
    db.delete(job)
    db.commit()
    return {"success": True}


@router.get("/sent", response_class=HTMLResponse)
async def sent_page(request: Request, db: Session = Depends(get_db)):
    logs = db.query(EmailLog).order_by(desc(EmailLog.created_at)).all()
    return _get_templates().TemplateResponse("sent.html", {"request": request, "logs": logs})


@router.get("/links", response_class=HTMLResponse)
async def links_page(request: Request):
    return _get_templates().TemplateResponse("links.html", {"request": request})


@router.get("/followups", response_class=HTMLResponse)
async def followups_page(request: Request, db: Session = Depends(get_db)):
    # フォローアップが設定されているリードを取得
    leads_with_followup = (
        db.query(Lead)
        .filter(Lead.followup_status.isnot(None))
        .order_by(desc(Lead.updated_at))
        .all()
    )

    # 各リードのステップ情報を付加
    followup_data = []
    for lead in leads_with_followup:
        steps = (
            db.query(FollowUpStep)
            .filter(FollowUpStep.lead_id == lead.id)
            .order_by(FollowUpStep.step_number)
            .all()
        )
        sent_count = sum(1 for s in steps if s.status == "sent")
        next_step = next((s for s in steps if s.status in ("pending", "ready")), None)
        followup_data.append({
            "lead": lead,
            "steps": steps,
            "sent_count": sent_count,
            "total_steps": len(steps),
            "next_step": next_step,
        })

    # 集計
    counts = {
        "active": sum(1 for d in followup_data if d["lead"].followup_status == "active"),
        "paused": sum(1 for d in followup_data if d["lead"].followup_status == "paused"),
        "completed": sum(1 for d in followup_data if d["lead"].followup_status == "completed"),
        "stopped": sum(1 for d in followup_data if d["lead"].followup_status == "stopped"),
    }

    return _get_templates().TemplateResponse("followups.html", {
        "request": request,
        "followup_data": followup_data,
        "counts": counts,
    })


@router.get("/roadmap", response_class=HTMLResponse)
async def roadmap_page(request: Request):
    return _get_templates().TemplateResponse("roadmap.html", {"request": request})
