"""Gmail IMAP返信自動検知サービス

送信済みリードの宛先アドレスと受信メールのFromを照合し、
返信を検知した場合はLead.status="replied"に更新 + フォローアップ停止 + LINE通知
"""
import asyncio
import imaplib
import email
import email.header
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.lead import Lead
from app.models.email_log import EmailLog

settings = get_settings()
logger = logging.getLogger(__name__)

# 処理済みメールIDを保持（重複通知防止、7日で自動クリーンアップ）
_processed_message_ids: dict[str, datetime] = {}
_PROCESSED_MAX_AGE_HOURS = 168  # 7日


def _decode_header_value(raw: str) -> str:
    """メールヘッダをデコード"""
    parts = email.header.decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="ignore"))
        else:
            decoded.append(data)
    return "".join(decoded)


def _extract_email_address(header_value: str) -> Optional[str]:
    """From/Toヘッダからメールアドレスを抽出"""
    match = re.search(r'[\w.+-]+@[\w.-]+\.\w+', header_value)
    return match.group(0).lower() if match else None


def _extract_body(msg: email.message.Message) -> str:
    """メールから本文テキストを抽出"""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(charset, errors="ignore")
            if content_type == "text/html":
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    html = payload.decode(charset, errors="ignore")
                    return re.sub(r'<[^>]+>', ' ', html)
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(charset, errors="ignore")
    return ""


def _check_replies_sync() -> list[dict]:
    """Gmail IMAPで受信メールをチェックし、リードからの返信を検知（同期処理）

    Returns:
        検知した返信のリスト [{lead_id, lead_domain, from_email, subject, body_preview, received_at}]
    """
    if not settings.GMAIL_ADDRESS or not settings.GMAIL_APP_PASSWORD:
        logger.debug("Gmail設定なし、返信検知スキップ")
        return []

    db: Session = SessionLocal()
    detected_replies: list[dict] = []

    try:
        # 古い処理済みIDをクリーンアップ
        cutoff = datetime.now() - timedelta(hours=_PROCESSED_MAX_AGE_HOURS)
        expired = [mid for mid, ts in _processed_message_ids.items() if ts < cutoff]
        for mid in expired:
            del _processed_message_ids[mid]

        # 送信済み or フォローアップ中のリードのメールアドレスを取得
        sent_leads = db.query(Lead).filter(
            or_(
                Lead.status.in_(["sent", "email_generated"]),
                Lead.followup_status == "active",
            ),
            Lead.contact_email.isnot(None),
        ).all()

        if not sent_leads:
            return []

        # 送信先メールアドレス → リードIDのマッピング
        email_to_lead: dict[str, Lead] = {}
        for lead in sent_leads:
            addr = lead.contact_email.strip().lower()
            email_to_lead[addr] = lead

        # IMAP接続
        mail_conn = imaplib.IMAP4_SSL("imap.gmail.com")
        mail_conn.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
        mail_conn.select("INBOX")

        # 直近3日以内のメールを検索
        since_date = (datetime.now() - timedelta(days=3)).strftime("%d-%b-%Y")
        _, msg_ids = mail_conn.search(None, f'(SINCE {since_date})')

        if not msg_ids[0]:
            mail_conn.logout()
            return []

        id_list = msg_ids[0].split()
        # 最新100件を処理
        for msg_id in id_list[-100:]:
            try:
                _, msg_data = mail_conn.fetch(msg_id, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                # Message-IDで重複チェック
                message_id = msg.get("Message-ID", "")
                if message_id in _processed_message_ids:
                    continue

                # 自分が送ったメールはスキップ
                from_header = msg.get("From", "")
                from_addr = _extract_email_address(from_header)
                if not from_addr or from_addr == settings.GMAIL_ADDRESS.lower():
                    continue

                # 送信先リードとマッチング
                if from_addr not in email_to_lead:
                    continue

                lead = email_to_lead[from_addr]
                subject = _decode_header_value(msg.get("Subject", ""))
                body = _extract_body(msg)
                body_preview = body[:500].strip() if body else ""

                # 受信日時
                date_str = msg.get("Date", "")
                received_at = datetime.now()

                detected_replies.append({
                    "lead_id": lead.id,
                    "lead_domain": lead.domain or lead.url,
                    "lead_title": lead.title or "",
                    "from_email": from_addr,
                    "subject": subject,
                    "body_preview": body_preview,
                    "received_at": received_at,
                })

                # 処理済みマーク
                _processed_message_ids[message_id] = datetime.now()

                # Lead更新: status → replied, followup停止
                lead.status = "replied"
                if lead.followup_status == "active":
                    lead.followup_status = "stopped"

                logger.info(f"返信検知: lead_id={lead.id}, from={from_addr}, subject={subject}")

            except Exception as e:
                logger.warning(f"メール解析エラー: {e}")
                continue

        db.commit()
        mail_conn.logout()

    except Exception as e:
        logger.error(f"返信検知IMAP接続エラー: {e}")
        db.rollback()
    finally:
        db.close()

    return detected_replies


async def check_replies() -> list[dict]:
    """非同期で返信チェックを実行"""
    return await asyncio.to_thread(_check_replies_sync)
