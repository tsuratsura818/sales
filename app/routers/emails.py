from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.lead import Lead
from app.models.email_log import EmailLog
from app.services import claude_service, gmail_service
from app.services.portfolio_service import get_portfolios_for_lead, format_portfolio_for_prompt
from app.schemas.lead import EmailUpdateRequest

router = APIRouter(prefix="/api", tags=["emails"])


class SendEmailRequest(BaseModel):
    to_email: str = ""


@router.post("/leads/{lead_id}/generate-email")
async def generate_email(lead_id: int, db: Session = Depends(get_db)):
    """Claude APIで営業メールを生成する"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="リードが見つかりません")
    if lead.status not in ("analyzed", "email_generated", "error"):
        raise HTTPException(status_code=400, detail="分析完了後にメールを生成してください")

    try:
        portfolios = get_portfolios_for_lead(db, lead)
        portfolio_text = format_portfolio_for_prompt(portfolios)
        subject, body = await claude_service.generate_email(lead, portfolio_text=portfolio_text)
        lead.generated_email_subject = subject
        lead.generated_email_body = body
        lead.status = "email_generated"
        db.commit()
        return {"subject": subject, "body": body}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"メール生成エラー: {e}")


@router.put("/leads/{lead_id}/email")
async def update_email(
    lead_id: int,
    request: EmailUpdateRequest,
    db: Session = Depends(get_db),
):
    """生成メールの内容を手動編集・保存する"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="リードが見つかりません")
    lead.generated_email_subject = request.subject
    lead.generated_email_body = request.body
    db.commit()
    return {"success": True}


@router.post("/leads/{lead_id}/send-email")
async def send_email(lead_id: int, req: SendEmailRequest = SendEmailRequest(), db: Session = Depends(get_db)):
    """Gmailでメールを送信する"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="リードが見つかりません")
    if not lead.generated_email_subject or not lead.generated_email_body:
        raise HTTPException(status_code=400, detail="まずメールを生成してください")

    to_address = req.to_email.strip() or lead.contact_email or ""
    if not to_address:
        raise HTTPException(status_code=400, detail="送信先メールアドレスを入力してください")

    # 入力されたアドレスをリードに保存
    if req.to_email.strip() and req.to_email.strip() != lead.contact_email:
        lead.contact_email = req.to_email.strip()

    log = EmailLog(
        lead_id=lead_id,
        to_address=to_address,
        subject=lead.generated_email_subject,
        body=lead.generated_email_body,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    try:
        entry_id = await gmail_service.send_email(
            to=to_address,
            subject=lead.generated_email_subject,
            body=lead.generated_email_body,
        )
        log.sent_at = datetime.now()
        log.outlook_message_id = entry_id
        lead.status = "sent"
        db.commit()
        return {"success": True, "message": f"{to_address} に送信しました"}
    except Exception as e:
        log.error_message = str(e)[:500]
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/email-logs")
async def list_email_logs(db: Session = Depends(get_db)):
    logs = db.query(EmailLog).order_by(desc(EmailLog.created_at)).all()
    return [
        {
            "id": log.id,
            "lead_id": log.lead_id,
            "to_address": log.to_address,
            "subject": log.subject,
            "sent_at": log.sent_at,
            "error_message": log.error_message,
        }
        for log in logs
    ]
