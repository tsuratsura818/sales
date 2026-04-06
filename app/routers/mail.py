"""メール配信管理ルーター（MailForge Supabase連携）"""
import logging
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.services import mailforge_client as mf

log = logging.getLogger("mail_router")
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

STATUS_JA = {
    "draft": "下書き", "generating": "生成中", "review": "レビュー待ち",
    "scheduled": "予約済み", "sending": "配信中", "paused": "一時停止",
    "completed": "完了", "cancelled": "キャンセル",
}

CC_STATUS_JA = {
    "pending": "待機中", "generating": "生成中", "generated": "生成済み",
    "queued": "キュー", "sending": "送信中", "sent": "送信済み",
    "failed": "失敗", "skipped": "スキップ", "bounced": "バウンス",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 画面系（HTML）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@router.get("/mail", response_class=HTMLResponse)
async def mail_dashboard(request: Request):
    try:
        stats = mf.get_stats()
        campaigns = stats.get("campaigns", [])
        # ステータスをPython側で日本語変換
        for c in campaigns:
            c["status_label"] = STATUS_JA.get(str(c.get("status", "")), str(c.get("status", "")))
        return templates.TemplateResponse("mail/dashboard.html", {
            "request": request,
            "total_contacts": stats.get("total_contacts", 0),
            "total_campaigns": stats.get("total_campaigns", 0),
            "active_campaigns": stats.get("active_campaigns", 0),
            "total_sent": stats.get("total_sent", 0),
            "campaigns": campaigns,
        })
    except Exception as e:
        log.error(f"/mail error: {e}", exc_info=True)
        return HTMLResponse(f"<h3>メール配信エラー</h3><pre>{e}</pre>", status_code=500)


@router.get("/mail/campaigns", response_class=HTMLResponse)
async def mail_campaigns(request: Request):
    campaigns = mf.get_campaigns()
    return templates.TemplateResponse("mail/campaigns.html", {
        "request": request,
        "campaigns": campaigns,
        "STATUS_JA": STATUS_JA,
    })


@router.get("/mail/campaigns/new", response_class=HTMLResponse)
async def mail_campaign_new(request: Request):
    lists = mf.get_contact_lists()
    return templates.TemplateResponse("mail/campaign_new.html", {
        "request": request,
        "lists": lists,
    })


@router.get("/mail/campaigns/{campaign_id}", response_class=HTMLResponse)
async def mail_campaign_detail(request: Request, campaign_id: str, tab: str = "overview"):
    campaign = mf.get_campaign(campaign_id)
    if not campaign:
        return HTMLResponse("キャンペーンが見つかりません", status_code=404)

    contacts = mf.get_campaign_contacts(campaign_id)
    logs = mf.get_send_logs(campaign_id=campaign_id)

    # ステータス集計
    status_counts = {}
    for cc in contacts:
        s = cc["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    return templates.TemplateResponse("mail/campaign_detail.html", {
        "request": request,
        "campaign": campaign,
        "contacts": contacts,
        "logs": logs,
        "status_counts": status_counts,
        "tab": tab,
        "STATUS_JA": STATUS_JA,
        "CC_STATUS_JA": CC_STATUS_JA,
    })


@router.get("/mail/contacts", response_class=HTMLResponse)
async def mail_contacts(request: Request, page: int = 1, search: str = "", list_id: str = ""):
    result = mf.get_contacts(page=page, search=search, list_id=list_id)
    lists = mf.get_contact_lists()
    return templates.TemplateResponse("mail/contacts.html", {
        "request": request,
        "contacts": result["contacts"],
        "total": result["total"],
        "page": page,
        "search": search,
        "list_id": list_id,
        "lists": lists,
    })


@router.get("/mail/logs", response_class=HTMLResponse)
async def mail_logs(request: Request):
    logs = mf.get_send_logs(limit=200)
    return templates.TemplateResponse("mail/logs.html", {
        "request": request,
        "logs": logs,
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API系（JSON）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@router.post("/api/mail/campaigns")
async def api_create_campaign(request: Request):
    body = await request.json()
    campaign = mf.create_campaign({
        "name": body["name"],
        "status": "review",
        "subject_template": body.get("subject_template", ""),
        "body_template": body.get("body_template", ""),
        "sender_name": body.get("sender_name", "西川"),
        "send_start_time": body.get("send_start_time", "09:00"),
        "send_end_time": body.get("send_end_time", "18:00"),
        "send_days": body.get("send_days", [1, 2, 3, 4, 5]),
        "min_interval_sec": body.get("min_interval_sec", 120),
        "max_interval_sec": body.get("max_interval_sec", 300),
        "list_id": body.get("list_id"),
        "total_contacts": body.get("total_contacts", 0),
    })
    return JSONResponse(campaign)


@router.patch("/api/mail/campaigns/{campaign_id}")
async def api_update_campaign(campaign_id: str, request: Request):
    body = await request.json()
    result = mf.update_campaign(campaign_id, body)
    return JSONResponse(result)


@router.get("/api/mail/contacts")
async def api_get_contacts(page: int = 1, search: str = "", list_id: str = ""):
    return JSONResponse(mf.get_contacts(page=page, search=search, list_id=list_id))


@router.post("/api/mail/leads-to-contacts")
async def api_leads_to_contacts(request: Request):
    """Salesのリード → MailForgeのコンタクトに一括変換"""
    body = await request.json()
    leads = body.get("leads", [])
    list_name = body.get("list_name", "Sales自動収集")

    # リスト作成
    contact_list = mf.create_contact_list(list_name, f"Salesから{len(leads)}件インポート")

    # コンタクト変換
    contacts = []
    for lead in leads:
        contacts.append({
            "email": lead.get("email", lead.get("contact_email", "")),
            "company_name": lead.get("company", lead.get("title", "")),
            "industry": lead.get("industry", ""),
            "website_url": lead.get("website", lead.get("url", "")),
            "notes": lead.get("proposal", lead.get("notes", "")),
            "custom_fields": {
                "source": "sales",
                "ec_status": lead.get("ec_status", ""),
                "location": lead.get("location", ""),
            },
        })

    result = mf.upsert_contacts(contacts, list_id=contact_list["id"])
    return JSONResponse({
        "list_id": contact_list["id"],
        "list_name": list_name,
        **result,
    })


@router.get("/api/mail/stats")
async def api_stats():
    return JSONResponse(mf.get_stats())
