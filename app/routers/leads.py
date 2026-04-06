import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.lead import Lead
from app.schemas.lead import LeadDetail, StatusUpdateRequest
from app.services.screenshot_service import capture_screenshots, get_screenshot_urls

router = APIRouter(prefix="/api", tags=["leads"])


@router.get("/leads")
async def list_leads(
    job_id: int | None = Query(None),
    status: str | None = Query(None),
    min_score: int = Query(0),
    sort: str = Query("score"),
    db: Session = Depends(get_db),
):
    query = db.query(Lead)

    if job_id:
        query = query.filter(Lead.search_job_id == job_id)
    if status:
        query = query.filter(Lead.status == status)
    if min_score > 0:
        query = query.filter(Lead.score >= min_score)

    if sort == "score":
        query = query.order_by(desc(Lead.score))
    elif sort == "created":
        query = query.order_by(desc(Lead.created_at))

    leads = query.all()
    return [_lead_to_dict(lead) for lead in leads]


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="リードが見つかりません")
    return _lead_to_dict(lead)


@router.patch("/leads/{lead_id}/status")
async def update_lead_status(
    lead_id: int,
    request: StatusUpdateRequest,
    db: Session = Depends(get_db),
):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="リードが見つかりません")
    lead.status = request.status
    db.commit()
    return {"success": True}


@router.delete("/leads/{lead_id}")
async def delete_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="リードが見つかりません")
    db.delete(lead)
    db.commit()
    return {"success": True}


@router.get("/leads/export/csv")
async def export_leads_csv(
    job_id: int | None = Query(None),
    min_score: int = Query(0),
    db: Session = Depends(get_db),
):
    query = db.query(Lead)
    if job_id:
        query = query.filter(Lead.search_job_id == job_id)
    if min_score > 0:
        query = query.filter(Lead.score >= min_score)
    query = query.filter(Lead.status != "excluded")
    leads = query.order_by(desc(Lead.score)).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "スコア", "ドメイン", "URL", "タイトル",
        "HTTPS", "モバイル対応", "著作権年", "ドメイン年齢",
        "CMS", "CMSバージョン", "PageSpeed",
        "メールアドレス", "問い合わせページ", "ステータス",
    ])
    for lead in leads:
        writer.writerow([
            lead.score,
            lead.domain or "",
            lead.url,
            lead.title or "",
            "非対応" if lead.is_https is False else ("対応" if lead.is_https else ""),
            "非対応" if lead.has_viewport is False else ("対応" if lead.has_viewport else ""),
            lead.copyright_year or "",
            f"{lead.domain_age_years}年" if lead.domain_age_years else "",
            lead.cms_type or "",
            lead.cms_version or "",
            lead.pagespeed_score or "",
            lead.contact_email or "",
            lead.contact_page_url or "",
            lead.status,
        ])

    output.seek(0)
    # BOM付きUTF-8でExcelで文字化けしないようにする
    bom = "\ufeff"
    content = bom + output.getvalue()

    filename = f"leads_job{job_id}.csv" if job_id else "leads_all.csv"
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/leads/{lead_id}/screenshot")
async def take_screenshot(lead_id: int, db: Session = Depends(get_db)):
    """手動でスクリーンショットを取得する"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="リードが見つかりません")

    result = await capture_screenshots(lead_id, lead.url)
    if not result["pc_url"] and not result["mobile_url"]:
        raise HTTPException(status_code=500, detail="スクリーンショットの取得に失敗しました")

    return result


@router.post("/leads/{lead_id}/meeting")
async def mark_meeting(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="リードが見つかりません")
    lead.status = "meeting"
    lead.meeting_scheduled_at = datetime.now()
    db.commit()
    return {"success": True}


@router.post("/leads/{lead_id}/closed")
async def mark_closed(
    lead_id: int,
    amount: int | None = Query(None),
    db: Session = Depends(get_db),
):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="リードが見つかりません")
    lead.status = "closed"
    lead.deal_closed_at = datetime.now()
    if amount is not None:
        lead.deal_amount = amount
    db.commit()
    return {"success": True}


@router.post("/leads/{lead_id}/meeting-email")
async def generate_meeting_email_endpoint(lead_id: int, db: Session = Depends(get_db)):
    """日程調整メール自動生成（Googleカレンダー空き時間連携）"""
    from app.services.meeting_scheduler import generate_meeting_email
    result = generate_meeting_email(db, lead_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/meeting/slots")
async def get_meeting_slots():
    """空き時間スロット一覧"""
    from app.services.meeting_scheduler import get_free_slots
    slots = get_free_slots()
    return {"slots": slots}


def _lead_to_dict(lead: Lead) -> dict:
    d = {c.name: getattr(lead, c.name) for c in lead.__table__.columns}
    if d.get("score_breakdown") and isinstance(d["score_breakdown"], str):
        try:
            d["score_breakdown"] = json.loads(d["score_breakdown"])
        except Exception:
            d["score_breakdown"] = {}
    return d
