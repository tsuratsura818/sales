"""
MailForge Supabase 直接接続クライアント（httpx版 — 追加パッケージ不要）
Sales → MailForge Supabase REST API にService Role Keyで接続
"""
import os
import logging
import httpx

log = logging.getLogger("mailforge_client")

SUPABASE_URL = os.getenv("MAILFORGE_SUPABASE_URL", "https://xpukjjmstticsubrxuit.supabase.co")
SUPABASE_KEY = os.getenv("MAILFORGE_SERVICE_KEY", "")
USER_ID = os.getenv("TSURATSURA_USER_ID", "999aedf8-f621-4a11-b23a-2ba0d51b7d21")
API_BASE = f"{SUPABASE_URL}/rest/v1"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def _get(table: str, params: dict = None) -> list[dict]:
    url = f"{API_BASE}/{table}"
    p = params or {}
    resp = httpx.get(url, headers=HEADERS, params=p, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _get_one(table: str, params: dict) -> dict | None:
    p = {**params, "limit": "1"}
    result = _get(table, p)
    return result[0] if result else None


def _post(table: str, data: dict) -> dict:
    url = f"{API_BASE}/{table}"
    resp = httpx.post(url, headers=HEADERS, json=data, timeout=15)
    resp.raise_for_status()
    return resp.json()[0] if resp.json() else {}


def _patch(table: str, data: dict, params: dict) -> dict:
    url = f"{API_BASE}/{table}"
    resp = httpx.patch(url, headers=HEADERS, json=data, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()[0] if resp.json() else {}


def _upsert(table: str, data: dict, on_conflict: str = "") -> dict:
    url = f"{API_BASE}/{table}"
    h = {**HEADERS, "Prefer": "return=representation,resolution=merge-duplicates"}
    if on_conflict:
        h["Prefer"] += f",on_conflict={on_conflict}"
    # upsertの場合はon_conflictをクエリパラメータで
    params = {}
    if on_conflict:
        params["on_conflict"] = on_conflict
    resp = httpx.post(url, headers={**HEADERS, "Prefer": "return=representation,resolution=merge-duplicates"}, json=data, params=params, timeout=15)
    if resp.status_code >= 400:
        log.warning(f"upsert error: {resp.text[:200]}")
    return resp.json()[0] if resp.status_code < 400 and resp.json() else {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ユーザープロフィール
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_user_profile() -> dict:
    return _get_one("users", {"id": f"eq.{USER_ID}"}) or {}


def update_user_profile(data: dict) -> bool:
    try:
        _patch("users", data, {"id": f"eq.{USER_ID}"})
        return True
    except Exception as e:
        log.error(f"Profile update error: {e}")
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# コンタクト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_contacts(page: int = 1, search: str = "", list_id: str = "") -> dict:
    limit = 50
    offset = (page - 1) * limit
    params = {
        "user_id": f"eq.{USER_ID}",
        "order": "created_at.desc",
        "offset": str(offset),
        "limit": str(limit),
    }
    if list_id:
        params["list_id"] = f"eq.{list_id}"
    if search:
        params["or"] = f"(email.ilike.%{search}%,company_name.ilike.%{search}%)"

    # count取得
    h = {**HEADERS, "Prefer": "count=exact"}
    resp = httpx.get(f"{API_BASE}/contacts", headers=h, params=params, timeout=15)
    total = int(resp.headers.get("content-range", "0-0/0").split("/")[-1]) if "content-range" in resp.headers else 0
    contacts = resp.json() if resp.status_code == 200 else []

    return {"contacts": contacts, "total": total, "page": page}


def get_contact_lists() -> list[dict]:
    return _get("contact_lists", {"user_id": f"eq.{USER_ID}", "order": "created_at.desc"})


def create_contact_list(name: str, description: str = "") -> dict:
    return _post("contact_lists", {"user_id": USER_ID, "name": name, "description": description})


def upsert_contacts(contacts: list[dict], list_id: str = "") -> dict:
    inserted = 0
    skipped = 0
    contact_ids: list[str] = []  # email順を保持
    email_to_id: dict[str, str] = {}
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
        result = _upsert("contacts", data, on_conflict="user_id,email")
        if result:
            inserted += 1
            cid = result.get("id")
            if cid:
                contact_ids.append(cid)
                email_to_id[c["email"].lower()] = cid
        else:
            skipped += 1
            # 既存contactを取得してIDをマップ
            existing = _get_one("contacts", {"user_id": f"eq.{USER_ID}", "email": f"eq.{c['email']}"})
            if existing:
                cid = existing.get("id")
                if cid:
                    contact_ids.append(cid)
                    email_to_id[c["email"].lower()] = cid
    return {
        "inserted": inserted,
        "skipped": skipped,
        "contact_ids": contact_ids,
        "email_to_id": email_to_id,
    }


def create_campaign_contacts(campaign_id: str, items: list[dict]) -> dict:
    """campaign_contacts に一括 INSERT する。

    items の各要素:
      {
        "contact_id": str (UUID),
        "personalized_subject": str,
        "personalized_body": str,
      }

    status='queued' で投入することで MailForge の AI生成cron をスキップし、
    そのまま送信cronで配信される。
    """
    if not items:
        return {"inserted": 0, "skipped": 0}

    # Supabase REST API は配列POSTで bulk insert 可能
    payload = []
    for it in items:
        if not it.get("contact_id"):
            continue
        payload.append({
            "campaign_id": campaign_id,
            "contact_id": it["contact_id"],
            "status": "queued",
            "personalized_subject": it.get("personalized_subject") or "",
            "personalized_body": it.get("personalized_body") or "",
        })

    if not payload:
        return {"inserted": 0, "skipped": len(items)}

    url = f"{API_BASE}/campaign_contacts"
    h = {**HEADERS, "Prefer": "return=representation,resolution=ignore-duplicates"}
    # ON CONFLICT (campaign_id, contact_id) を ignore する設定
    params = {"on_conflict": "campaign_id,contact_id"}
    resp = httpx.post(url, headers=h, json=payload, params=params, timeout=30)
    if resp.status_code >= 400:
        log.warning(f"campaign_contacts insert error: {resp.status_code} {resp.text[:300]}")
        return {"inserted": 0, "skipped": len(payload), "error": resp.text[:200]}
    inserted_rows = resp.json() if resp.status_code < 400 else []
    return {"inserted": len(inserted_rows), "skipped": len(payload) - len(inserted_rows)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# キャンペーン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_campaigns() -> list[dict]:
    return _get("campaigns", {"user_id": f"eq.{USER_ID}", "order": "created_at.desc"})


def get_campaign(campaign_id: str) -> dict | None:
    return _get_one("campaigns", {"id": f"eq.{campaign_id}", "user_id": f"eq.{USER_ID}"})


def create_campaign(data: dict) -> dict:
    data["user_id"] = USER_ID
    return _post("campaigns", data)


def update_campaign(campaign_id: str, data: dict) -> dict:
    return _patch("campaigns", data, {"id": f"eq.{campaign_id}", "user_id": f"eq.{USER_ID}"})


def get_campaign_contacts(campaign_id: str) -> list[dict]:
    # campaign_contactsを取得し、contactsをJOIN
    ccs = _get("campaign_contacts", {
        "campaign_id": f"eq.{campaign_id}",
        "order": "created_at",
        "select": "*,contact:contacts(email,company_name,person_name)",
    })
    return ccs


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 送信ログ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_send_logs(campaign_id: str = "", limit: int = 100) -> list[dict]:
    params = {
        "user_id": f"eq.{USER_ID}",
        "order": "sent_at.desc",
        "limit": str(limit),
    }
    if campaign_id:
        params["campaign_id"] = f"eq.{campaign_id}"
    return _get("send_logs", params)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 統計
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_stats() -> dict:
    # contacts count
    h = {**HEADERS, "Prefer": "count=exact"}
    cr = httpx.get(f"{API_BASE}/contacts", headers=h, params={"user_id": f"eq.{USER_ID}", "limit": "0"}, timeout=15)
    total_contacts = int(cr.headers.get("content-range", "0-0/0").split("/")[-1]) if "content-range" in cr.headers else 0

    campaigns = _get("campaigns", {"user_id": f"eq.{USER_ID}", "order": "created_at.desc"})
    active = [c for c in campaigns if c.get("status") == "sending"]

    # sent count
    lr = httpx.get(f"{API_BASE}/send_logs", headers=h, params={"user_id": f"eq.{USER_ID}", "status": "eq.sent", "limit": "0"}, timeout=15)
    total_sent = int(lr.headers.get("content-range", "0-0/0").split("/")[-1]) if "content-range" in lr.headers else 0

    # 開封・クリック合計
    total_opens = sum(int(c.get("open_count") or 0) for c in campaigns)
    total_clicks = sum(int(c.get("click_count") or 0) for c in campaigns)
    open_rate = round(total_opens / total_sent * 100, 1) if total_sent > 0 else 0.0
    click_rate = round(total_clicks / total_sent * 100, 1) if total_sent > 0 else 0.0

    return {
        "total_contacts": total_contacts,
        "total_campaigns": len(campaigns),
        "active_campaigns": len(active),
        "total_sent": total_sent,
        "total_opens": total_opens,
        "total_clicks": total_clicks,
        "open_rate": open_rate,
        "click_rate": click_rate,
        "campaigns": campaigns,
    }
