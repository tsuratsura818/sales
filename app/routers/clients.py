"""既存クライアントサイトの管理 + 健康診断"""
import asyncio
import json
import logging
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.client_site import ClientSite, HealthCheckResult
from app.services.health_check_service import check_and_save

logger = logging.getLogger(__name__)
router = APIRouter(tags=["clients"])


def _get_templates():
    from main import templates
    return templates


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


@router.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, db: Session = Depends(get_db)):
    """クライアント一覧ページ"""
    sites = db.query(ClientSite).order_by(desc(ClientSite.created_at)).all()
    counts = {
        "total": len(sites),
        "active": sum(1 for s in sites if s.is_active),
        "critical": sum(1 for s in sites if s.last_status == "critical"),
        "warning": sum(1 for s in sites if s.last_status == "warning"),
        "ok": sum(1 for s in sites if s.last_status == "ok"),
    }
    return _get_templates().TemplateResponse(request, "clients.html", {
        "sites": sites,
        "counts": counts,
    })


@router.get("/api/clients")
async def list_clients(db: Session = Depends(get_db)):
    sites = db.query(ClientSite).order_by(desc(ClientSite.created_at)).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "url": s.url,
            "contact_email": s.contact_email,
            "contact_name": s.contact_name,
            "industry": s.industry,
            "is_active": s.is_active,
            "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
            "last_status": s.last_status,
        }
        for s in sites
    ]


@router.post("/api/clients")
async def create_client(request: Request, db: Session = Depends(get_db)):
    """新規追加"""
    body = await request.json()
    name = (body.get("name") or "").strip()
    url = _normalize_url(body.get("url") or "")
    if not name or not url:
        raise HTTPException(400, "name と url は必須です")
    # 重複チェック
    if db.query(ClientSite).filter(ClientSite.url == url).first():
        raise HTTPException(409, "そのURLは既に登録されています")

    site = ClientSite(
        name=name,
        url=url,
        contact_email=body.get("contact_email"),
        contact_name=body.get("contact_name"),
        industry=body.get("industry"),
        notes=body.get("notes"),
    )
    db.add(site)
    db.commit()
    db.refresh(site)
    return {"id": site.id, "url": site.url, "name": site.name}


@router.post("/api/clients/bulk")
async def bulk_create_clients(request: Request, db: Session = Depends(get_db)):
    """改行区切りでまとめて追加。各行は「name | url」または「url のみ」"""
    body = await request.json()
    raw = (body.get("text") or "").strip()
    if not raw:
        raise HTTPException(400, "text 必須")
    added = 0
    skipped = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # 「name | url」形式 or url単体
        if "|" in line:
            name, url = [p.strip() for p in line.split("|", 1)]
        elif "\t" in line:
            name, url = [p.strip() for p in line.split("\t", 1)]
        else:
            url = line
            try:
                name = urlparse(_normalize_url(url)).hostname or url
            except Exception:
                name = url

        url = _normalize_url(url)
        if not url:
            skipped += 1
            continue
        if db.query(ClientSite).filter(ClientSite.url == url).first():
            skipped += 1
            continue
        db.add(ClientSite(name=name, url=url))
        added += 1
    db.commit()
    return {"added": added, "skipped": skipped}


@router.put("/api/clients/{cid}")
async def update_client(cid: int, request: Request, db: Session = Depends(get_db)):
    site = db.query(ClientSite).filter(ClientSite.id == cid).first()
    if not site:
        raise HTTPException(404, "見つかりません")
    body = await request.json()
    for k in ("name", "contact_email", "contact_name", "industry", "notes"):
        if k in body:
            setattr(site, k, body[k])
    if "is_active" in body:
        site.is_active = bool(body["is_active"])
    if "url" in body:
        site.url = _normalize_url(body["url"])
    db.commit()
    return {"success": True}


@router.delete("/api/clients/{cid}")
async def delete_client(cid: int, db: Session = Depends(get_db)):
    site = db.query(ClientSite).filter(ClientSite.id == cid).first()
    if not site:
        raise HTTPException(404, "見つかりません")
    db.query(HealthCheckResult).filter(HealthCheckResult.client_site_id == cid).delete()
    db.delete(site)
    db.commit()
    return {"success": True}


@router.post("/api/clients/{cid}/check")
async def run_check_now(cid: int, db: Session = Depends(get_db)):
    """単一クライアントを今すぐチェック"""
    site = db.query(ClientSite).filter(ClientSite.id == cid).first()
    if not site:
        raise HTTPException(404, "見つかりません")
    record = await check_and_save(site, db)
    return {
        "success": True,
        "status": record.status,
        "ssl_days_left": record.ssl_days_left,
        "pagespeed_mobile": record.pagespeed_mobile,
        "pagespeed_desktop": record.pagespeed_desktop,
        "issues": json.loads(record.issues_json or "[]"),
    }


@router.post("/api/clients/check-all")
async def run_check_all(db: Session = Depends(get_db)):
    """全アクティブクライアントを今すぐチェック（バックグラウンド）"""
    from app.tasks.health_check_scheduler import run_now
    asyncio.create_task(run_now())
    return {"success": True, "message": "バックグラウンドで実行を開始しました"}


@router.get("/api/clients/{cid}/results")
async def list_results(cid: int, db: Session = Depends(get_db)):
    rows = db.query(HealthCheckResult).filter(
        HealthCheckResult.client_site_id == cid
    ).order_by(desc(HealthCheckResult.checked_at)).limit(12).all()
    return [
        {
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
            "status": r.status,
            "ssl_days_left": r.ssl_days_left,
            "pagespeed_mobile": r.pagespeed_mobile,
            "pagespeed_desktop": r.pagespeed_desktop,
            "has_form": r.has_form,
            "cms": r.cms,
            "cms_version": r.cms_version,
            "issues": json.loads(r.issues_json or "[]"),
        }
        for r in rows
    ]
