from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.lead import Lead
from app.models.follow_up import FollowUpStep
from app.services import followup_service
from app.schemas.lead import EmailUpdateRequest

router = APIRouter(prefix="/api", tags=["followups"])


@router.post("/leads/{lead_id}/followup/start")
async def start_followup(lead_id: int, db: Session = Depends(get_db)):
    """フォローアップシーケンスを開始する"""
    try:
        steps = await followup_service.start_sequence(lead_id, db)
        return {"success": True, "steps": steps}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/leads/{lead_id}/followup/cancel")
async def cancel_followup(lead_id: int, db: Session = Depends(get_db)):
    """フォローアップを停止する"""
    try:
        result = followup_service.cancel_sequence(lead_id, db)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/leads/{lead_id}/followup/pause")
async def pause_followup(lead_id: int, db: Session = Depends(get_db)):
    """フォローアップを一時停止する"""
    try:
        result = followup_service.pause_sequence(lead_id, db)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/leads/{lead_id}/followup/resume")
async def resume_followup(lead_id: int, db: Session = Depends(get_db)):
    """フォローアップを再開する"""
    try:
        result = followup_service.resume_sequence(lead_id, db)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/leads/{lead_id}/replied")
async def mark_replied(lead_id: int, db: Session = Depends(get_db)):
    """返信ありとしてマークする"""
    try:
        result = followup_service.mark_replied(lead_id, db)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/leads/{lead_id}/followup/steps")
async def get_followup_steps(lead_id: int, db: Session = Depends(get_db)):
    """フォローアップステップ一覧を取得する"""
    steps = (
        db.query(FollowUpStep)
        .filter(FollowUpStep.lead_id == lead_id)
        .order_by(FollowUpStep.step_number)
        .all()
    )
    return [
        {
            "id": s.id,
            "step_number": s.step_number,
            "scheduled_at": s.scheduled_at.isoformat() if s.scheduled_at else None,
            "status": s.status,
            "email_subject": s.email_subject,
            "email_body": s.email_body,
            "sent_at": s.sent_at.isoformat() if s.sent_at else None,
            "error_message": s.error_message,
        }
        for s in steps
    ]


@router.put("/followup-steps/{step_id}/email")
async def update_step_email(
    step_id: int,
    request: EmailUpdateRequest,
    db: Session = Depends(get_db),
):
    """ステップメールの内容を手動編集する"""
    step = db.query(FollowUpStep).filter(FollowUpStep.id == step_id).first()
    if not step:
        raise HTTPException(status_code=404, detail="ステップが見つかりません")
    if step.status == "sent":
        raise HTTPException(status_code=400, detail="送信済みのステップは編集できません")

    step.email_subject = request.subject
    step.email_body = request.body
    step.status = "ready"
    db.commit()
    return {"success": True}


@router.post("/followup-steps/{step_id}/send-now")
async def send_step_now(step_id: int, db: Session = Depends(get_db)):
    """ステップメールを即時送信する"""
    step = db.query(FollowUpStep).filter(FollowUpStep.id == step_id).first()
    if not step:
        raise HTTPException(status_code=404, detail="ステップが見つかりません")
    if step.status == "sent":
        raise HTTPException(status_code=400, detail="既に送信済みです")

    lead = step.lead

    # 未生成ならまず生成
    if step.status in ("pending", "generating"):
        try:
            await followup_service.generate_step_email(lead, step, db)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"メール生成エラー: {e}")

    try:
        await followup_service.send_step(step, db)
        return {"success": True, "message": f"ステップ{step.step_number}を送信しました"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
