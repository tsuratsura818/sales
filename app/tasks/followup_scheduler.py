import asyncio
import logging
from datetime import datetime

from sqlalchemy import and_
from app.database import SessionLocal
from app.models.follow_up import FollowUpStep
from app.models.lead import Lead
from app.services import followup_service

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # 秒


async def followup_scheduler() -> None:
    """バックグラウンドでフォローアップメールの送信予定をチェックし自動送信する"""
    # 起動直後は少し待つ（DB初期化完了を待つ）
    await asyncio.sleep(10)
    logger.info("フォローアップスケジューラ開始")

    while True:
        try:
            db = SessionLocal()
            try:
                now = datetime.now()

                # 送信予定時刻を過ぎていて、リードがactive状態のステップを取得
                due_steps = (
                    db.query(FollowUpStep)
                    .join(Lead)
                    .filter(
                        FollowUpStep.status.in_(["pending", "ready"]),
                        FollowUpStep.scheduled_at <= now,
                        Lead.followup_status == "active",
                    )
                    .order_by(FollowUpStep.step_number)
                    .all()
                )

                for step in due_steps:
                    try:
                        # 未生成ならClaude APIで生成
                        if step.status == "pending":
                            logger.info(
                                f"フォローアップ生成: lead={step.lead_id} step={step.step_number}"
                            )
                            await followup_service.generate_step_email(
                                step.lead, step, db
                            )

                        # ready なら送信
                        if step.status == "ready":
                            logger.info(
                                f"フォローアップ送信: lead={step.lead_id} step={step.step_number}"
                            )
                            await followup_service.send_step(step, db)

                        # 連続送信を避けるため少し待つ
                        await asyncio.sleep(5)

                    except Exception as e:
                        logger.error(
                            f"フォローアップエラー: lead={step.lead_id} step={step.step_number}: {e}"
                        )
                        # step.statusはサービス側でerrorに設定済み
            finally:
                db.close()
        except Exception as e:
            logger.error(f"スケジューラエラー: {e}")

        await asyncio.sleep(POLL_INTERVAL)
