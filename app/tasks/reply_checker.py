"""返信検知バックグラウンドタスク（5分間隔）

あわせて、日次アウトリーチの送信メールとその返信を専用フォルダ
（SellBuddy/営業送信済み・SellBuddy/営業返信）に振り分ける。
どちらも軽いIMAP操作で数秒で終わるため、Renderが再起動しても
次のループでやり直せる（COPY は冪等）。
"""
import asyncio
import logging

from app.services.reply_detector import check_replies
from app.services.line_service import push_reply_notification

logger = logging.getLogger(__name__)

REPLY_CHECK_INTERVAL_SEC = 300  # 5分
# 振り分けは毎回やる必要がないので、返信チェック6回に1回（＝約30分間隔）
FILE_EVERY_N_LOOPS = 6


async def reply_checker():
    """5分間隔でGmail受信箱をチェックし、リードからの返信を検知→LINE通知"""
    logger.info("返信検知タスク開始")
    await asyncio.sleep(30)  # 起動直後は30秒待機

    loop_count = 0
    while True:
        loop_count += 1
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

        # 日次アウトリーチのメールを専用フォルダに振り分ける
        if loop_count % FILE_EVERY_N_LOOPS == 1:
            try:
                from app.services.mail_folder_service import file_outreach_mail
                result = await asyncio.to_thread(file_outreach_mail)
                if result.get("sent") or result.get("replies"):
                    logger.info(
                        f"営業メール振り分け: 送信{result['sent']}件 / 返信{result['replies']}件"
                    )
            except Exception as e:
                logger.error(f"営業メール振り分けエラー: {e}")

        await asyncio.sleep(REPLY_CHECK_INTERVAL_SEC)
