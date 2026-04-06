"""インバウンドWebhookルーター

POST /api/webhook/inbound — WordPress/soreiineからのリード受信
GET  /api/inbound — インバウンドリード一覧
PATCH /api/inbound/{id}/status — ステータス更新
GET  /inbound — インバウンドリードページ
"""
import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.inbound import InboundLead
from app.services.line_service import push_inbound_notification

router = APIRouter(tags=["webhook"])
logger = logging.getLogger(__name__)
settings = get_settings()


def _get_templates():
    from main import templates
    return templates


class InboundWebhookData(BaseModel):
    email: str
    name: str | None = None
    company: str | None = None
    phone: str | None = None
    message: str | None = None
    source: str = "wordpress"
    source_url: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    diagnostic_result: str | None = None


@router.post("/api/webhook/inbound")
async def receive_inbound(
    data: InboundWebhookData,
    request: Request,
    x_webhook_secret: str | None = Header(None),
    db: Session = Depends(get_db),
):
    """WordPress/soreiineからインバウンドリードを受信"""
    # Webhook認証
    if settings.WEBHOOK_SECRET:
        if x_webhook_secret != settings.WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Webhook認証エラー")
    else:
        logger.warning("WEBHOOK_SECRET未設定: 認証なしで受信中")

    # 重複チェック
    existing = db.query(InboundLead).filter(
        InboundLead.email == data.email,
        InboundLead.source == data.source,
    ).first()
    if existing:
        logger.info(f"重複インバウンド: {data.email} from {data.source}")
        return {"status": "duplicate", "id": existing.id}

    # 保存
    lead = InboundLead(
        email=data.email,
        name=data.name,
        company=data.company,
        phone=data.phone,
        message=data.message,
        source=data.source,
        source_url=data.source_url,
        utm_source=data.utm_source,
        utm_medium=data.utm_medium,
        utm_campaign=data.utm_campaign,
        diagnostic_result=data.diagnostic_result,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    logger.info(f"インバウンドリード受信: {data.email} from {data.source}")

    # LINE通知
    try:
        await push_inbound_notification(
            lead_id=lead.id,
            email=lead.email,
            name=lead.name or "",
            company=lead.company or "",
            source=lead.source,
            message=lead.message or "",
        )
        lead.notified = 1
        db.commit()
    except Exception as e:
        logger.error(f"インバウンドLINE通知エラー: {e}")

    return {"status": "ok", "id": lead.id}


ALLOWED_INBOUND_STATUSES = {"new", "contacted", "qualified", "converted", "lost"}


class StatusUpdate(BaseModel):
    status: str


@router.patch("/api/inbound/{lead_id}/status")
async def update_inbound_status(lead_id: int, data: StatusUpdate, db: Session = Depends(get_db)):
    """インバウンドリードのステータス更新"""
    if data.status not in ALLOWED_INBOUND_STATUSES:
        raise HTTPException(status_code=400, detail=f"無効なステータス: {data.status}")
    lead = db.query(InboundLead).filter(InboundLead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="リードが見つかりません")
    lead.status = data.status
    db.commit()
    return {"success": True}


@router.get("/api/inbound")
async def list_inbound(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """インバウンドリード一覧"""
    query = db.query(InboundLead).order_by(desc(InboundLead.created_at))
    if status:
        query = query.filter(InboundLead.status == status)
    leads = query.limit(100).all()

    return {
        "leads": [
            {
                "id": l.id,
                "email": l.email,
                "name": l.name,
                "company": l.company,
                "phone": l.phone,
                "message": l.message,
                "source": l.source,
                "source_url": l.source_url,
                "status": l.status,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in leads
        ]
    }


@router.get("/inbound", response_class=HTMLResponse)
async def inbound_page(request: Request):
    return _get_templates().TemplateResponse(request, "inbound.html", {})
