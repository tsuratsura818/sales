import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.lead import Lead
from app.models.follow_up import FollowUpStep
from app.models.email_log import EmailLog
from app.services import gmail_service, proposal_service
from app.services.portfolio_service import get_portfolios_for_lead, format_portfolio_for_prompt

logger = logging.getLogger(__name__)

# ステップ間隔（日数）
STEP_DELAYS = {
    1: 0,   # 即時（既存メール流用）
    2: 3,   # 3日後
    3: 7,   # 7日後
}


async def start_sequence(lead_id: int, db: Session) -> list[dict]:
    """フォローアップシーケンスを開始する（3ステップ作成）"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise ValueError("リードが見つかりません")
    if not lead.contact_email:
        raise ValueError("送信先メールアドレスがありません")
    if lead.followup_status == "active":
        raise ValueError("既にフォローアップが進行中です")

    now = datetime.now()
    steps = []

    for step_num, delay_days in STEP_DELAYS.items():
        scheduled = now + timedelta(days=delay_days)
        step = FollowUpStep(
            lead_id=lead_id,
            step_number=step_num,
            scheduled_at=scheduled,
            status="ready" if step_num == 1 else "pending",
            email_subject=lead.generated_email_subject if step_num == 1 else None,
            email_body=lead.generated_email_body if step_num == 1 else None,
        )
        db.add(step)
        steps.append(step)

    lead.followup_status = "active"
    db.commit()

    return [
        {
            "id": s.id,
            "step_number": s.step_number,
            "scheduled_at": s.scheduled_at.isoformat(),
            "status": s.status,
        }
        for s in steps
    ]


async def generate_step_email(lead: Lead, step: FollowUpStep, db: Session) -> None:
    """ローカル Claude Code でフォローアップメールを生成してステップに保存する"""
    step.status = "generating"
    db.commit()

    # 過去の送信済み件名を収集
    previous_subjects = []
    for s in sorted(lead.follow_up_steps, key=lambda x: x.step_number):
        if s.step_number < step.step_number and s.email_subject:
            previous_subjects.append(s.email_subject)

    try:
        portfolios = get_portfolios_for_lead(db, lead)
        portfolio_text = format_portfolio_for_prompt(portfolios)
        subject, body = await proposal_service.generate_followup_email(
            lead=lead,
            step_number=step.step_number,
            previous_subjects=previous_subjects,
            portfolio_text=portfolio_text,
        )
        step.email_subject = subject
        step.email_body = body
        step.status = "ready"
        db.commit()
    except Exception as e:
        step.status = "error"
        step.error_message = f"メール生成エラー: {str(e)[:400]}"
        db.commit()
        raise


async def send_step(step: FollowUpStep, db: Session) -> None:
    """ステップメールをGmailで送信する"""
    lead = step.lead
    if not lead.contact_email:
        step.status = "error"
        step.error_message = "送信先メールアドレスなし"
        db.commit()
        return

    # EmailLog 作成（既存の送信フローと一貫性を保つ）
    log = EmailLog(
        lead_id=lead.id,
        to_address=lead.contact_email,
        subject=step.email_subject,
        body=step.email_body,
        follow_up_step_id=step.id,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    try:
        await gmail_service.send_email(
            to=lead.contact_email,
            subject=step.email_subject,
            body=step.email_body,
            tracking_id=log.tracking_id or "",
        )
        log.sent_at = datetime.now()
        step.status = "sent"
        step.sent_at = datetime.now()
        db.commit()

        # 全ステップ送信完了チェック
        all_steps = db.query(FollowUpStep).filter(
            FollowUpStep.lead_id == lead.id
        ).all()
        if all(s.status in ("sent", "cancelled") for s in all_steps):
            lead.followup_status = "completed"
            db.commit()

        logger.info(f"フォローアップ送信完了: lead={lead.id} step={step.step_number}")
    except Exception as e:
        log.error_message = str(e)[:500]
        step.status = "error"
        step.error_message = f"送信エラー: {str(e)[:400]}"
        db.commit()
        raise


def cancel_sequence(lead_id: int, db: Session) -> dict:
    """フォローアップシーケンスを停止する"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise ValueError("リードが見つかりません")

    cancelled = 0
    steps = db.query(FollowUpStep).filter(
        FollowUpStep.lead_id == lead_id,
        FollowUpStep.status.in_(["pending", "ready", "generating"]),
    ).all()
    for step in steps:
        step.status = "cancelled"
        cancelled += 1

    lead.followup_status = "stopped"
    db.commit()
    return {"cancelled_steps": cancelled}


def pause_sequence(lead_id: int, db: Session) -> dict:
    """フォローアップを一時停止する"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise ValueError("リードが見つかりません")
    lead.followup_status = "paused"
    db.commit()
    return {"status": "paused"}


def resume_sequence(lead_id: int, db: Session) -> dict:
    """フォローアップを再開する"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise ValueError("リードが見つかりません")
    lead.followup_status = "active"
    db.commit()
    return {"status": "active"}


def mark_replied(lead_id: int, db: Session) -> dict:
    """返信ありとしてマークし、フォローアップを停止する"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise ValueError("リードが見つかりません")

    lead.status = "replied"
    lead.followup_status = "stopped"

    # 残りのステップをキャンセル
    steps = db.query(FollowUpStep).filter(
        FollowUpStep.lead_id == lead_id,
        FollowUpStep.status.in_(["pending", "ready", "generating"]),
    ).all()
    for step in steps:
        step.status = "cancelled"

    db.commit()
    return {"status": "replied"}
