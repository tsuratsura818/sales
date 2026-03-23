from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.portfolio import Portfolio
from app.services.portfolio_service import INDUSTRY_CATEGORIES, SERVICE_TYPES

router = APIRouter(tags=["portfolios"])


def _get_templates():
    from main import templates
    return templates


# --- Pydantic スキーマ ---

class PortfolioCreate(BaseModel):
    title: str
    client_name: str | None = None
    url: str | None = None
    description: str | None = None
    industry_category: str
    service_type: str = "web_renewal"
    result_summary: str | None = None


class PortfolioUpdate(BaseModel):
    title: str | None = None
    client_name: str | None = None
    url: str | None = None
    description: str | None = None
    industry_category: str | None = None
    service_type: str | None = None
    result_summary: str | None = None
    is_active: bool | None = None


# --- HTML ページ ---

@router.get("/portfolios", response_class=HTMLResponse)
async def portfolios_page(request: Request, db: Session = Depends(get_db)):
    portfolios = db.query(Portfolio).order_by(desc(Portfolio.created_at)).all()
    return _get_templates().TemplateResponse(request, "portfolios.html", {
        "portfolios": portfolios,
        "industry_categories": INDUSTRY_CATEGORIES,
        "service_types": SERVICE_TYPES,
    })


# --- JSON API ---

@router.get("/api/portfolios")
async def list_portfolios(
    industry: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Portfolio)
    if industry:
        query = query.filter(Portfolio.industry_category == industry)
    portfolios = query.order_by(desc(Portfolio.created_at)).all()
    return [
        {
            "id": p.id,
            "title": p.title,
            "client_name": p.client_name,
            "url": p.url,
            "description": p.description,
            "industry_category": p.industry_category,
            "service_type": p.service_type,
            "result_summary": p.result_summary,
            "is_active": p.is_active,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in portfolios
    ]


@router.post("/api/portfolios")
async def create_portfolio(data: PortfolioCreate, db: Session = Depends(get_db)):
    portfolio = Portfolio(
        title=data.title,
        client_name=data.client_name or None,
        url=data.url or None,
        description=data.description or None,
        industry_category=data.industry_category,
        service_type=data.service_type,
        result_summary=data.result_summary or None,
    )
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return {"success": True, "id": portfolio.id}


@router.put("/api/portfolios/{portfolio_id}")
async def update_portfolio(
    portfolio_id: int,
    data: PortfolioUpdate,
    db: Session = Depends(get_db),
):
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="ポートフォリオが見つかりません")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(portfolio, field, value)

    db.commit()
    return {"success": True}


@router.delete("/api/portfolios/{portfolio_id}")
async def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="ポートフォリオが見つかりません")
    db.delete(portfolio)
    db.commit()
    return {"success": True}
