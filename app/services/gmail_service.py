import asyncio
import imaplib
import email
import logging
import re
import smtplib
import time
from email.mime.text import MIMEText
from typing import Optional

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _fetch_verification_code_sync(
    sender_filter: str,
    subject_filter: str,
    code_pattern: str = r'\b(\d{6})\b',
    max_wait_sec: int = 60,
    poll_interval: int = 5,
) -> Optional[str]:
    """GmailからIMAPで認証コードを取得（同期処理）

    Args:
        sender_filter: 送信者のメールアドレス（部分一致）
        subject_filter: 件名のキーワード
        code_pattern: コード抽出用の正規表現
        max_wait_sec: 最大待機秒数
        poll_interval: ポーリング間隔（秒）
    """
    deadline = time.time() + max_wait_sec
    search_start = time.time()

    while time.time() < deadline:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
            mail.select("INBOX")

            # 直近のメールを検索（送信者フィルタ）
            _, msg_ids = mail.search(None, f'(FROM "{sender_filter}" UNSEEN)')
            if not msg_ids[0]:
                # UNSEENで見つからなければ直近のメールも確認
                _, msg_ids = mail.search(None, f'(FROM "{sender_filter}")')

            if msg_ids[0]:
                # 最新のメールから確認
                id_list = msg_ids[0].split()
                for msg_id in reversed(id_list[-5:]):
                    _, msg_data = mail.fetch(msg_id, "(RFC822)")
                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)

                    # 件名チェック
                    subject = msg.get("Subject", "")
                    decoded_subject = str(
                        email.header.decode_header(subject)[0][0],
                        errors="ignore"
                    ) if isinstance(email.header.decode_header(subject)[0][0], bytes) else email.header.decode_header(subject)[0][0]

                    if subject_filter not in decoded_subject:
                        continue

                    # 本文からコードを抽出
                    body_text = _extract_body(msg)
                    match = re.search(code_pattern, body_text)
                    if match:
                        code = match.group(1)
                        logger.info(f"認証コード取得成功: {code[:2]}****")
                        mail.logout()
                        return code

            mail.logout()
        except Exception as e:
            logger.warning(f"IMAP取得エラー: {e}")

        remaining = deadline - time.time()
        if remaining > 0:
            logger.info(f"認証コード待機中... (残り{int(remaining)}秒)")
            time.sleep(min(poll_interval, remaining))

    logger.error(f"認証コードが{max_wait_sec}秒以内に届きませんでした")
    return None


def _extract_body(msg: email.message.Message) -> str:
    """メールから本文テキストを抽出"""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="ignore")
            if content_type == "text/html":
                charset = part.get_content_charset() or "utf-8"
                html = part.get_payload(decode=True).decode(charset, errors="ignore")
                # HTMLタグを除去して簡易テキスト化
                return re.sub(r'<[^>]+>', ' ', html)
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, errors="ignore")
    return ""


async def fetch_verification_code(
    sender_filter: str,
    subject_filter: str,
    code_pattern: str = r'\b(\d{6})\b',
    max_wait_sec: int = 60,
) -> Optional[str]:
    """非同期で認証コードを取得"""
    return await asyncio.to_thread(
        _fetch_verification_code_sync,
        sender_filter, subject_filter, code_pattern, max_wait_sec,
    )


def _send_email_sync(to: str, subject: str, body: str) -> str:
    """Gmail SMTP でメール送信（同期処理）"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.GMAIL_ADDRESS
    msg["To"] = to
    msg["Bcc"] = settings.GMAIL_ADDRESS

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
            # BCC含む全宛先に送信
            server.send_message(msg)
        return ""
    except Exception as e:
        raise RuntimeError(f"Gmail送信エラー: {e}")


async def send_email(to: str, subject: str, body: str) -> str:
    """非同期で Gmail メール送信を実行する"""
    return await asyncio.to_thread(_send_email_sync, to, subject, body)
