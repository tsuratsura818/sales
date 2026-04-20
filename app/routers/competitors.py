import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.lead import Lead
from app.models.competitor import CompetitorAnalysis
from app.services import competitor_service, proposal_service
from app.services.portfolio_service import get_portfolios_for_lead, format_portfolio_for_prompt

router = APIRouter(prefix="/api", tags=["competitors"])


@router.post("/leads/{lead_id}/competitor-analysis")
async def start_competitor_analysis(lead_id: int, db: Session = Depends(get_db)):
    """競合分析を実行する"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="リードが見つかりません")
    if lead.status not in ("analyzed", "email_generated", "sent", "replied"):
        raise HTTPException(status_code=400, detail="分析完了後に競合分析を実行してください")

    try:
        analysis = await competitor_service.run_competitor_analysis(lead_id, db)
        summary = {}
        if analysis.comparison_summary:
            try:
                summary = json.loads(analysis.comparison_summary)
            except Exception:
                pass
        return {
            "success": True,
            "id": analysis.id,
            "status": analysis.status,
            "competitor_count": analysis.competitor_count,
            "comparison_summary": summary,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"競合分析エラー: {e}")


@router.get("/leads/{lead_id}/competitor-analysis")
async def get_competitor_analysis(lead_id: int, db: Session = Depends(get_db)):
    """最新の競合分析結果を取得する"""
    analysis = (
        db.query(CompetitorAnalysis)
        .filter(CompetitorAnalysis.lead_id == lead_id)
        .order_by(desc(CompetitorAnalysis.created_at))
        .first()
    )
    if not analysis:
        return {"exists": False}

    summary = {}
    if analysis.comparison_summary:
        try:
            summary = json.loads(analysis.comparison_summary)
        except Exception:
            pass

    return {
        "exists": True,
        "id": analysis.id,
        "status": analysis.status,
        "search_query": analysis.search_query,
        "competitor_count": analysis.competitor_count,
        "comparison_summary": summary,
        "serpapi_calls_used": analysis.serpapi_calls_used,
        "error_message": analysis.error_message,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


@router.post("/leads/{lead_id}/generate-competitor-email")
async def generate_competitor_email(lead_id: int, db: Session = Depends(get_db)):
    """競合比較データを使った営業メールを生成する"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="リードが見つかりません")

    analysis = (
        db.query(CompetitorAnalysis)
        .filter(
            CompetitorAnalysis.lead_id == lead_id,
            CompetitorAnalysis.status == "completed",
        )
        .order_by(desc(CompetitorAnalysis.created_at))
        .first()
    )
    if not analysis or not analysis.comparison_summary:
        raise HTTPException(status_code=400, detail="先に競合分析を実行してください")

    comparison_data = json.loads(analysis.comparison_summary)

    try:
        portfolios = get_portfolios_for_lead(db, lead)
        portfolio_text = format_portfolio_for_prompt(portfolios)
        subject, body = await proposal_service.generate_competitor_email(
            lead=lead,
            comparison_data=comparison_data,
            portfolio_text=portfolio_text,
        )
        lead.generated_email_subject = subject
        lead.generated_email_body = body
        if lead.status == "analyzed":
            lead.status = "email_generated"
        db.commit()
        return {"subject": subject, "body": body}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"メール生成エラー: {e}")
