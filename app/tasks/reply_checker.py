"""返信検知バックグラウンドタスク（5分間隔）"""
import asyncio
import logging

from app.services.reply_detector import check_replies
from app.services.line_service import push_reply_notification

logger = logging.getLogger(__name__)

REPLY_CHECK_INTERVAL_SEC = 300  # 5分


async def reply_checker():
    """5分間隔でGmail受信箱をチェックし、リードからの返信を検知→LINE通知"""
    logger.info("返信検知タスク開始")
    await asyncio.sleep(30)  # 起動直後は30秒待機

    while True:
        try:
            replies = await check_replies()
            if replies:
                logger.info(f"返信検知: {len(replies)}件")
                for reply in replies:
                    try:
                        await push_reply_notification(
                            lead_id=reply["lead_id"],
                            lead_domain=reply["lead_domain"],
                            lead_title=reply["lead_title"],
                            from_email=reply["from_email"],
                            subject=reply["subject"],
                            body_preview=reply["body_preview"],
                        )
                    except Exception as e:
                        logger.error(f"返信LINE通知エラー: {e}")
        except Exception as e:
            logger.error(f"返信検知タスクエラー: {e}")

        await asyncio.sleep(REPLY_CHECK_INTERVAL_SEC)
