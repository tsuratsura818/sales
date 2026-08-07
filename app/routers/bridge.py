"""ローカルClaudeブリッジ(Mac 24/7 + cloudflaredトンネル)のURL管理。

Mac側の常駐スクリプトが、cloudflaredの公開URLを起動/再接続のたびに
`POST /api/bridge/register` で登録する（共有シークレットで認証）。
フロントは `GET /api/bridge/config` で現在のURL+シークレットを取得して叩く。
（このエンドポイントはBasic認証配下なので、シークレットは認証済みユーザーのみ取得できる）
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request

from app.config import get_settings
from app.database import SessionLocal
from app.models.app_settings import AppSettings

router = APIRouter(tags=["bridge"])
settings = get_settings()
JST = timezone(timedelta(hours=9))


def _get_cfg(db) -> AppSettings:
    cfg = db.query(AppSettings).first()
    if not cfg:
        cfg = AppSettings()
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


@router.post("/api/bridge/register")
async def register_bridge(request: Request):
    """Mac常駐スクリプトが現在のトンネルURLを登録する（共有シークレット必須）。"""
    secret = request.headers.get("X-Bridge-Secret", "")
    if not settings.BRIDGE_SHARED_SECRET or secret != settings.BRIDGE_SHARED_SECRET:
        return {"success": False, "error": "unauthorized"}
    body = await request.json()
    url = (body.get("url") or "").strip().rstrip("/")
    if not url.startswith("https://"):
        return {"success": False, "error": "invalid url"}
    db = SessionLocal()
    try:
        cfg = _get_cfg(db)
        cfg.local_bridge_url = url
        cfg.local_bridge_updated_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        db.commit()
    finally:
        db.close()
    return {"success": True, "url": url}


@router.get("/api/bridge/config")
async def bridge_config():
    """フロント用: 現在のブリッジURL + シークレット + 最終更新。

    Basic認証配下なので、認証済みユーザーのみがシークレットを取得できる。
    """
    db = SessionLocal()
    try:
        cfg = db.query(AppSettings).first()
        url = getattr(cfg, "local_bridge_url", None) if cfg else None
        updated = getattr(cfg, "local_bridge_updated_at", None) if cfg else None
    finally:
        db.close()
    return {
        "url": url,
        "secret": settings.BRIDGE_SHARED_SECRET or "",
        "updated_at": updated,
    }
