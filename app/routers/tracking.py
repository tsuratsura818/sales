"""メール開封・クリックトラッキング エンドポイント

GET /track/open?t=<tracking_id>
  → 1x1 透過 GIF を返す。EmailLog.opened_at / open_count + EmailOpen を記録

GET /track/click?t=<tracking_id>&url=<encoded_url>
  → 元URLへ 302 リダイレクト。EmailLog.clicked_at / click_count + LinkClick を記録
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.email_log import EmailLog, EmailOpen, LinkClick

router = APIRouter(tags=["tracking"])
log = logging.getLogger("tracking")

# 1x1 透過GIF (43バイト)
_PIXEL_GIF = base64.b64decode(
    b"R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


def _no_cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


@router.get("/track/open")
async def track_open(t: str = "", request: Request = None, db: Session = Depends(get_db)):
    """開封ピクセルエンドポイント。常に 1x1 GIF を返す(失敗してもメール表示を壊さない)"""
    if t:
        try:
            log_row = db.query(EmailLog).filter(EmailLog.tracking_id == t).first()
            if log_row:
                ua = request.headers.get("user-agent", "")[:300] if request else ""
                # 一部のメールクライアント(特にGmail)はプロキシで先読みしてくる
                # 実用上問題ないので素直に記録
                ip = request.client.host if request and request.client else None

                log_row.open_count = (log_row.open_count or 0) + 1
                if not log_row.opened_at:
                    log_row.opened_at = datetime.now()
                db.add(EmailOpen(
                    email_log_id=log_row.id,
                    ip_address=ip,
                    user_agent=ua,
                ))
                db.commit()
        except Exception as e:
            log.warning(f"track_open error: {e}")
            db.rollback()

    return Response(content=_PIXEL_GIF, media_type="image/gif", headers=_no_cache_headers())


@router.get("/track/click")
async def track_click(
    t: str = "",
    url: str = "",
    request: Request = None,
    db: Session = Depends(get_db),
):
    """クリックリダイレクト。常に元URLへリダイレクト(失敗してもユーザー体験を壊さない)"""
    target = unquote(url) if url else "/"

    if t and url:
        try:
            log_row = db.query(EmailLog).filter(EmailLog.tracking_id == t).first()
            if log_row:
                ua = request.headers.get("user-agent", "")[:300] if request else ""
                ip = request.client.host if request and request.client else None

                log_row.click_count = (log_row.click_count or 0) + 1
                if not log_row.clicked_at:
                    log_row.clicked_at = datetime.now()
                db.add(LinkClick(
                    email_log_id=log_row.id,
                    url=target[:500],
                    ip_address=ip,
                    user_agent=ua,
                ))
                db.commit()
        except Exception as e:
            log.warning(f"track_click error: {e}")
            db.rollback()

    # 不正なURLでも安全側にフォールバック
    if not target.startswith(("http://", "https://")):
        target = "https://sales-6g78.onrender.com/"

    return RedirectResponse(url=target, status_code=302)
