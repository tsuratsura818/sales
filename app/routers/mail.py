"""メール配信管理ルーター（MailForge Supabase連携）"""
import logging
import traceback
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


def _render(name: str, **ctx) -> HTMLResponse:
    """Jinja2キャッシュバグ回避のためtemplate.renderを直接使用"""
    try:
        tmpl = templates.env.get_template(name)
        html = tmpl.render(**ctx)
        return HTMLResponse(html)
    except Exception as e:
        tb = traceback.format_exc()
        log.error(f"Template render error {name}: {tb}")
        return HTMLResponse(f"<h3>テンプレートエラー: {name}</h3><pre>{tb}</pre>", status_code=500)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 画面系（HTML）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@router.get("/mail", response_class=HTMLResponse)
async def mail_dashboard(request: Request):
    try:
        stats = mf.get_stats()
        campaigns = stats.get("campaigns", [])
        for c in campaigns:
            c["status_label"] = STATUS_JA.get(str(c.get("status", "")), str(c.get("status", "")))
        return _render("mail/dashboard.html",
            request=request,
            total_contacts=stats.get("total_contacts", 0),
            total_campaigns=stats.get("total_campaigns", 0),
            active_campaigns=stats.get("active_campaigns", 0),
            total_sent=stats.get("total_sent", 0),
            total_opens=stats.get("total_opens", 0),
            total_clicks=stats.get("total_clicks", 0),
            open_rate=stats.get("open_rate", 0.0),
            click_rate=stats.get("click_rate", 0.0),
            campaigns=campaigns,
        )
    except Exception as e:
        tb = traceback.format_exc()
        return HTMLResponse(f"<h3>メール配信エラー</h3><pre>{tb}</pre>", status_code=500)


@router.get("/mail/campaigns", response_class=HTMLResponse)
async def mail_campaigns(request: Request):
    campaigns = mf.get_campaigns()
    for c in campaigns:
        c["status_label"] = STATUS_JA.get(str(c.get("status", "")), str(c.get("status", "")))
    return _render("mail/campaigns.html", request=request, campaigns=campaigns)


@router.get("/mail/campaigns/new", response_class=HTMLResponse)
async def mail_campaign_new(request: Request):
    lists = mf.get_contact_lists()
    return _render("mail/campaign_new.html", request=request, lists=lists)


@router.get("/mail/campaigns/{campaign_id}", response_class=HTMLResponse)
async def mail_campaign_detail(request: Request, campaign_id: str, tab: str = "overview"):
    campaign = mf.get_campaign(campaign_id)
    if not campaign:
        return HTMLResponse("キャンペーンが見つかりません", status_code=404)

    campaign["status_label"] = STATUS_JA.get(str(campaign.get("status", "")), str(campaign.get("status", "")))
    contacts = mf.get_campaign_contacts(campaign_id)
    logs = mf.get_send_logs(campaign_id=campaign_id)

    status_counts = {}
    for cc in contacts:
        s = str(cc.get("status", ""))
        label = CC_STATUS_JA.get(s, s)
        status_counts[label] = status_counts.get(label, 0) + 1
        cc["status_label"] = label

    for lg in logs:
        s = str(lg.get("status", ""))
        if s == "sent":
            lg["status_label"] = "送信済み"
        elif s == "bounced":
            lg["status_label"] = "バウンス"
        else:
            lg["status_label"] = "失敗"

    return _render("mail/campaign_detail.html",
        request=request, campaign=campaign, contacts=contacts, logs=logs,
        status_counts=status_counts, tab=tab,
    )


@router.get("/mail/contacts", response_class=HTMLResponse)
async def mail_contacts(request: Request, page: int = 1, search: str = "", list_id: str = ""):
    result = mf.get_contacts(page=page, search=search, list_id=list_id)
    lists = mf.get_contact_lists()
    return _render("mail/contacts.html",
        request=request,
        contacts=result.get("contacts", []),
        total=result.get("total", 0),
        page=page, search=search, list_id=list_id, lists=lists,
    )


@router.get("/mail/settings", response_class=HTMLResponse)
async def mail_settings(request: Request):
    user = mf.get_user_profile()
    return _render("mail/settings.html", request=request, user=user, message="", message_type="")


@router.post("/mail/settings", response_class=HTMLResponse)
async def mail_settings_post(request: Request):
    form = await request.form()
    data = {
        "smtp_host": form.get("smtp_host", ""),
        "smtp_port": int(form.get("smtp_port", 465)),
        "smtp_user": form.get("smtp_user", ""),
        "smtp_secure": "smtp_secure" in form,
        "sender_name": form.get("sender_name", ""),
        "sender_company": form.get("sender_company", ""),
        "sender_address": form.get("sender_address", ""),
        "sender_phone": form.get("sender_phone", ""),
        "sender_email": form.get("sender_email", ""),
    }
    # パスワードは入力があった場合のみ更新
    if form.get("smtp_pass"):
        data["smtp_pass"] = form.get("smtp_pass")

    success = mf.update_user_profile(data)
    user = mf.get_user_profile()
    msg = "保存しました" if success else "保存に失敗しました"
    msg_type = "success" if success else "error"
    return _render("mail/settings.html", request=request, user=user, message=msg, message_type=msg_type)


@router.get("/mail/logs", response_class=HTMLResponse)
async def mail_logs(request: Request, source: str = ""):
    """送信ログ統合ビュー(MailForge配信 + Gmail直送)

    クエリ `source=mailforge|gmail|`(空=全部) でフィルタ可能。
    """
    from app.database import SessionLocal
    from app.models.email_log import EmailLog

    logs: list[dict] = []

    # MailForge 配信ログ
    if source in ("", "mailforge"):
        mf_logs = mf.get_send_logs(limit=200) or []
        for lg in mf_logs:
            s = str(lg.get("status", ""))
            label = "送信済み" if s == "sent" else ("バウンス" if s == "bounced" else "失敗")
            logs.append({
                "source": "mailforge",
                "source_label": "MF配信",
                "to_email": lg.get("to_email", ""),
                "subject": lg.get("subject", ""),
                "status_label": label,
                "sent_at": lg.get("sent_at") or "",
                "error_message": lg.get("error_message") or "",
                "lead_id": None,
            })

    # Gmail 直送ログ (sales.db EmailLog) — トラッキング情報付き
    if source in ("", "gmail"):
        db = SessionLocal()
        try:
            gm_logs = db.query(EmailLog).order_by(EmailLog.created_at.desc()).limit(200).all()
            for lg in gm_logs:
                if lg.error_message:
                    label = "失敗"
                elif lg.sent_at:
                    label = "送信済み"
                else:
                    label = "保留"
                logs.append({
                    "source": "gmail",
                    "source_label": "Gmail直送",
                    "to_email": lg.to_address,
                    "subject": lg.subject or "",
                    "status_label": label,
                    "sent_at": lg.sent_at.isoformat() if lg.sent_at else "",
                    "error_message": lg.error_message or "",
                    "lead_id": lg.lead_id,
                    "open_count": lg.open_count or 0,
                    "click_count": lg.click_count or 0,
                    "opened_at": lg.opened_at.isoformat() if lg.opened_at else "",
                    "clicked_at": lg.clicked_at.isoformat() if lg.clicked_at else "",
                })
        finally:
            db.close()

    # 送信日時で降順ソート (空文字は末尾)
    logs.sort(key=lambda x: x.get("sent_at") or "", reverse=True)

    return _render("mail/logs.html", request=request, logs=logs, current_source=source)


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
    body = await request.json()
    leads = body.get("leads", [])
    list_name = body.get("list_name", "Sales自動収集")
    contact_list = mf.create_contact_list(list_name, f"Salesから{len(leads)}件インポート")
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
    return JSONResponse({"list_id": contact_list["id"], "list_name": list_name, **result})


@router.get("/api/mail/stats")
async def api_stats():
    return JSONResponse(mf.get_stats())
