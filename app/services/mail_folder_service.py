"""日次アウトリーチのメールを専用フォルダ（Gmailラベル）に振り分ける。

日次アウトリーチは MailForge が `nishikawa@tsuratsura.com` の Gmail SMTP から
送信する。MailForge は別アプリなので送信処理には手を入れられないが、
送信済みメールは Gmail が自動的に「送信済みメール」に保存し、返信は同じ
受信トレイに届くため、IMAP から後追いで振り分けられる。

- 送信したメール → `SellBuddy/営業送信済み`
- その返信       → `SellBuddy/営業返信`

「誰に送ったか」は pipeline_results の queued_at / campaign_id で分かるので、
それと突き合わせて該当メールだけにラベルを付ける。

Gmail では IMAP の COPY がラベル付与にあたる。受信トレイからは外さないので、
返信を見落とす心配はなく、ラベル側でも一覧できる。
"""
from __future__ import annotations

import email
import email.header
import imaplib
import logging
import re
from datetime import datetime, timedelta

from app.config import get_settings

logger = logging.getLogger("mail_folder")
settings = get_settings()

FOLDER_SENT = "SellBuddy/営業送信済み"
FOLDER_REPLY = "SellBuddy/営業返信"

# 何日ぶんさかのぼって振り分けるか
LOOKBACK_DAYS = 14


# ── Gmail の IMAP フォルダ名は modified UTF-7 ────────────────
def imap_utf7_encode(name: str) -> str:
    """フォルダ名を modified UTF-7 に変換する（RFC 3501）。

    通常の UTF-7 から、'+' を '&'、'/' を ',' に置き換えたもの。
    素の '&' は '&-' にエスケープする。
    """
    out: list[str] = []
    buf: list[str] = []

    def flush():
        if not buf:
            return
        chunk = "".join(buf).encode("utf-7").decode("ascii")
        # Python の utf-7 は "+....-" 形式。'+' → '&'、'/' → ','
        chunk = chunk.replace("+", "&", 1).replace("/", ",")
        if not chunk.endswith("-"):
            chunk += "-"
        out.append(chunk)
        buf.clear()

    for ch in name:
        if ch == "&":
            flush()
            out.append("&-")
        elif 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append(ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def imap_utf7_decode(name: str) -> str:
    """modified UTF-7 のフォルダ名を元に戻す（ログ表示用）"""
    def _sub(m: re.Match) -> str:
        body = m.group(1)
        if body == "":
            return "&"
        return ("+" + body.replace(",", "/") + "-").encode("ascii").decode("utf-7")

    return re.sub(r"&([^-]*)-", _sub, name)


def _decode_header(raw: str) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    out = []
    for data, charset in parts:
        if isinstance(data, bytes):
            out.append(data.decode(charset or "utf-8", errors="ignore"))
        else:
            out.append(data)
    return "".join(out)


def _addresses(header_value: str) -> set[str]:
    return {a.lower() for a in re.findall(r"[\w.+-]+@[\w.-]+\.\w+", header_value or "")}


def _connect() -> imaplib.IMAP4_SSL:
    addr = settings.GMAIL_ADDRESS
    pw = settings.GMAIL_APP_PASSWORD
    if not (addr and pw):
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定です")
    m = imaplib.IMAP4_SSL("imap.gmail.com")
    m.login(addr, pw)
    return m


def _find_special(m: imaplib.IMAP4_SSL, flag: str) -> str | None:
    """\\Sent などの特殊フラグが付いたフォルダ名を返す（日本語UIでも動くように）"""
    typ, data = m.list()
    if typ != "OK":
        return None
    for raw in data:
        line = raw.decode("utf-8", "replace")
        if flag in line:
            mm = re.search(r'"[^"]*"\s+"?([^"]+)"?$', line)
            if mm:
                return mm.group(1)
    return None


def ensure_folders(m: imaplib.IMAP4_SSL) -> None:
    """振り分け先ラベルが無ければ作る"""
    typ, data = m.list()
    existing = {raw.decode("utf-8", "replace").rsplit(" ", 1)[-1].strip('"') for raw in (data or [])}
    for folder in (FOLDER_SENT, FOLDER_REPLY):
        enc = imap_utf7_encode(folder)
        if enc in existing:
            continue
        typ, resp = m.create(f'"{enc}"')
        if typ == "OK":
            logger.info(f"フォルダを作成: {folder}")
        else:
            logger.warning(f"フォルダ作成に失敗: {folder} {resp}")


def _outreach_recipients(days: int = LOOKBACK_DAYS) -> set[str]:
    """日次アウトリーチで送信キューに入れた宛先アドレス"""
    from app.database import SessionLocal
    from app.models.pipeline import PipelineResult

    since = datetime.utcnow() - timedelta(days=days)
    db = SessionLocal()
    try:
        rows = (
            db.query(PipelineResult.email)
            .filter(
                PipelineResult.queued_at.isnot(None),
                PipelineResult.queued_at >= since,
            )
            .all()
        )
        return {e.lower() for (e,) in rows if e}
    finally:
        db.close()


def _file_folder(
    m: imaplib.IMAP4_SSL,
    source_folder: str,
    targets: set[str],
    dest_folder: str,
    match_header: str,
    days: int,
) -> int:
    """source_folder を走査し、指定ヘッダが targets に一致するメールへラベルを付ける"""
    typ, _ = m.select(f'"{source_folder}"', readonly=False)
    if typ != "OK":
        logger.warning(f"フォルダを開けません: {imap_utf7_decode(source_folder)}")
        return 0

    since = (datetime.utcnow() - timedelta(days=days)).strftime("%d-%b-%Y")
    typ, data = m.search(None, f'(SINCE {since})')
    if typ != "OK" or not data or not data[0]:
        return 0

    dest_enc = imap_utf7_encode(dest_folder)
    filed = 0
    for num in data[0].split():
        typ, msg_data = m.fetch(num, f"(BODY.PEEK[HEADER.FIELDS ({match_header})])")
        if typ != "OK" or not msg_data or not msg_data[0]:
            continue
        raw = msg_data[0][1]
        if not raw:
            continue
        header_value = _decode_header(raw.decode("utf-8", "replace"))
        if not (_addresses(header_value) & targets):
            continue
        typ, _ = m.copy(num, f'"{dest_enc}"')
        if typ == "OK":
            filed += 1
    return filed


def file_outreach_mail(days: int = LOOKBACK_DAYS) -> dict:
    """送信メールと返信を専用フォルダに振り分ける。付けた件数を返す。"""
    targets = _outreach_recipients(days)
    if not targets:
        logger.info("振り分け対象の送信先がありません")
        return {"sent": 0, "replies": 0, "targets": 0}

    m = _connect()
    try:
        ensure_folders(m)
        sent_folder = _find_special(m, "\\Sent") or "[Gmail]/Sent Mail"
        sent = _file_folder(m, sent_folder, targets, FOLDER_SENT, "To", days)
        replies = _file_folder(m, "INBOX", targets, FOLDER_REPLY, "From", days)
        logger.info(f"振り分け: 送信{sent}件 / 返信{replies}件 (対象{len(targets)}アドレス)")
        return {"sent": sent, "replies": replies, "targets": len(targets)}
    finally:
        try:
            m.logout()
        except Exception:
            pass
