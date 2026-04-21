"""バウンス検知バックグラウンドタスク

Gmail IMAP を定期的に監視し、"Mail Delivery Subsystem" からの
バウンス通知を検出して、配信停止リストに自動追加する。

実行: main.py の lifespan から asyncio.create_task() で起動。
"""
from __future__ import annotations

import asyncio
import email as email_parser
import imaplib
import logging
import re
from datetime import datetime, timedelta

from app.config import get_settings

log = logging.getLogger("bounce_checker")
settings = get_settings()

# 1時間ごとにチェック
CHECK_INTERVAL_SEC = 3600

# バウンス元の典型的な From アドレス
BOUNCE_SENDERS = [
    "mailer-daemon@",
    "postmaster@",
    "Mail Delivery Subsystem",
]

# 本文からメールアドレスを抽出する正規表現
EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")

# ハードバウンスの典型的な文言
HARD_BOUNCE_KEYWORDS = [
    "user unknown",
    "no such user",
    "address not found",
    "recipient address rejected",
    "does not exist",
    "5.1.1",
    "5.1.10",
    "5.2.1",
    "5.4.1",
]


def _scan_inbox_sync() -> list[dict]:
    """IMAP で INBOX を走査し、バウンス通知を検出 → 辞書リスト返す"""
    if not settings.GMAIL_ADDRESS or not settings.GMAIL_APP_PASSWORD:
        return []

    results: list[dict] = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
        mail.select("INBOX")

        # 過去24時間の mailer-daemon メール
        since = (datetime.now() - timedelta(days=1)).strftime("%d-%b-%Y")
        status, data = mail.search(None, f'(FROM "mailer-daemon" SINCE {since})')
        if status != "OK":
            mail.logout()
            return []

        ids = (data[0] or b"").split()
        for msg_id in ids[-50:]:  # 直近50件
            try:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_parser.message_from_bytes(raw)
                subj = str(msg.get("Subject", "")).lower()
                frm = str(msg.get("From", "")).lower()

                # From が mailer-daemon / postmaster
                if not any(s in frm for s in ("mailer-daemon", "postmaster", "mail delivery")):
                    continue

                # 本文取得
                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                body_text += part.get_payload(decode=True).decode(
                                    part.get_content_charset() or "utf-8",
                                    errors="ignore",
                                )
                            except Exception:
                                continue
                else:
                    try:
                        body_text = msg.get_payload(decode=True).decode(
                            msg.get_content_charset() or "utf-8",
                            errors="ignore",
                        )
                    except Exception:
                        body_text = ""

                body_lower = body_text.lower()
                is_hard = any(kw in body_lower for kw in HARD_BOUNCE_KEYWORDS)

                # 本文からメールアドレス抽出(自分宛は除外)
                addrs = [
                    a.lower() for a in EMAIL_RE.findall(body_text)
                    if "@" in a
                    and not a.lower().endswith(settings.GMAIL_ADDRESS.lower())
                    and not any(s in a.lower() for s in ("mailer-daemon", "postmaster"))
                ]
                # 最初に出てくる宛先を「バウンスしたアドレス」とみなす
                if addrs:
                    results.append({
                        "email": addrs[0],
                        "reason": "bounced_hard" if is_hard else "bounced_soft",
                        "subject": subj[:200],
                        "snippet": body_text[:500],
                    })
            except Exception as e:
                log.debug(f"bounce parse error: {e}")
                continue

        mail.logout()
    except Exception as e:
        log.warning(f"IMAP scan error: {e}")

    return results


async def bounce_checker() -> None:
    """バックグラウンドループ: 1時間ごとにバウンス検知 → 配信停止追加"""
    await asyncio.sleep(60)  # 起動から1分待ってから最初のチェック
    while True:
        try:
            log.info("バウンスチェック実行")
            bounces = await asyncio.to_thread(_scan_inbox_sync)

            if bounces:
                from app.database import SessionLocal
                from app.services.suppression_service import add_suppression
                db = SessionLocal()
                try:
                    added = 0
                    for b in bounces:
                        if add_suppression(
                            b["email"], db,
                            reason=b["reason"],
                            source="gmail_imap",
                            detail=f'{b["subject"]} / {b["snippet"][:300]}',
                        ):
                            added += 1
                    if added:
                        log.info(f"新規バウンス登録: {added}件 / 検出 {len(bounces)}件")
                finally:
                    db.close()
            else:
                log.debug("バウンスなし")
        except Exception as e:
            log.error(f"bounce_checker iteration error: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SEC)
