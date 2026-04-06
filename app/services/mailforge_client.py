"""
MailForge Supabase 直接接続クライアント
Sales → MailForge Supabase (xpukjjmstticsubrxuit) にService Role Keyで接続
"""
import os
import logging
from supabase import create_client, Client

log = logging.getLogger("mailforge_client")

SUPABASE_URL = os.getenv("MAILFORGE_SUPABASE_URL", "https://xpukjjmstticsubrxuit.supabase.co")
SUPABASE_KEY = os.getenv("MAILFORGE_SERVICE_KEY", "")
USER_ID = os.getenv("TSURATSURA_USER_ID", "999aedf8-f621-4a11-b23a-2ba0d51b7d21")


def get_client() -> Client:
    if not SUPABASE_KEY:
        raise RuntimeError("MAILFORGE_SERVICE_KEY が設定されていません")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# コンタクト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_contacts(page: int = 1, search: str = "", list_id: str = "") -> dict:
    client = get_client()
    limit = 50
    offset = (page - 1) * limit

    query = client.table("contacts").select("*", count="exact").eq("user_id", USER_ID).order("created_at", desc=True).range(offset, offset + limit - 1)
    if list_id:
        query = query.eq("list_id", list_id)
    if search:
        query = query.or_(f"email.ilike.%{search}%,company_name.ilike.%{search}%")

    result = query.execute()
    return {"contacts": result.data, "total": result.count, "page": page}


def get_contact_lists() -> list[dict]:
    client = get_client()
    result = client.table("contact_lists").select("*").eq("user_id", USER_ID).order("created_at", desc=True).execute()
    return result.data


def create_contact_list(name: str, description: str = "") -> dict:
    client = get_client()
    result = client.table("contact_lists").insert({
        "user_id": USER_ID,
        "name": name,
        "description": description,
    }).execute()
    return result.data[0]


def upsert_contacts(contacts: list[dict], list_id: str = "") -> dict:
    client = get_client()
    inserted = 0
    skipped = 0
    for c in contacts:
        data = {
            "user_id": USER_ID,
            "email": c["email"],
            "company_name": c.get("company_name", ""),
            "industry": c.get("industry", ""),
            "website_url": c.get("website_url", ""),
            "notes": c.get("notes", ""),
            "consent_type": "public_website",
        }
        if list_id:
            data["list_id"] = list_id
        if c.get("custom_fields"):
            data["custom_fields"] = c["custom_fields"]
        try:
            client.table("contacts").upsert(data, on_conflict="user_id,email").execute()
            inserted += 1
        except Exception as e:
            log.warning(f"upsert error {c['email']}: {e}")
            skipped += 1
    return {"inserted": inserted, "skipped": skipped}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# キャンペーン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_campaigns() -> list[dict]:
    client = get_client()
    result = client.table("campaigns").select("*").eq("user_id", USER_ID).order("created_at", desc=True).execute()
    return result.data


def get_campaign(campaign_id: str) -> dict | None:
    client = get_client()
    result = client.table("campaigns").select("*").eq("id", campaign_id).eq("user_id", USER_ID).single().execute()
    return result.data


def create_campaign(data: dict) -> dict:
    client = get_client()
    data["user_id"] = USER_ID
    result = client.table("campaigns").insert(data).execute()
    return result.data[0]


def update_campaign(campaign_id: str, data: dict) -> dict:
    client = get_client()
    result = client.table("campaigns").update(data).eq("id", campaign_id).eq("user_id", USER_ID).execute()
    return result.data[0] if result.data else {}


def get_campaign_contacts(campaign_id: str) -> list[dict]:
    client = get_client()
    result = client.table("campaign_contacts").select("*, contact:contacts(email, company_name, person_name)").eq("campaign_id", campaign_id).order("created_at").execute()
    return result.data


def create_campaign_contacts(campaign_id: str, contact_ids: list[str], subject_fn=None, body_fn=None) -> int:
    """キャンペーンにコンタクトを紐付け + メール文面生成"""
    client = get_client()
    created = 0
    for cid in contact_ids:
        # コンタクト情報取得
        contact = client.table("contacts").select("*").eq("id", cid).single().execute().data
        if not contact:
            continue

        subject = subject_fn(contact) if subject_fn else ""
        body = body_fn(contact) if body_fn else ""

        try:
            client.table("campaign_contacts").insert({
                "campaign_id": campaign_id,
                "contact_id": cid,
                "status": "generated" if subject else "pending",
                "personalized_subject": subject,
                "personalized_body": body,
            }).execute()
            created += 1
        except Exception:
            pass
    return created


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 送信ログ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_send_logs(campaign_id: str = "", limit: int = 100) -> list[dict]:
    client = get_client()
    query = client.table("send_logs").select("*").eq("user_id", USER_ID).order("sent_at", desc=True).limit(limit)
    if campaign_id:
        query = query.eq("campaign_id", campaign_id)
    result = query.execute()
    return result.data


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 統計
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_stats() -> dict:
    client = get_client()
    contacts = client.table("contacts").select("*", count="exact").eq("user_id", USER_ID).execute()
    campaigns = client.table("campaigns").select("*").eq("user_id", USER_ID).execute()
    logs = client.table("send_logs").select("*", count="exact").eq("user_id", USER_ID).eq("status", "sent").execute()

    active = [c for c in (campaigns.data or []) if c["status"] == "sending"]
    return {
        "total_contacts": contacts.count or 0,
        "total_campaigns": len(campaigns.data or []),
        "active_campaigns": len(active),
        "total_sent": logs.count or 0,
        "campaigns": campaigns.data or [],
    }
