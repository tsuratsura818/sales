"""Google Calendar API クライアント - サービスアカウント方式（キャッシュ付き）"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone

from app.config import get_settings

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# キャッシュ（TTL: 5分）
_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 300

# サービスオブジェクトを再利用
_service_cache = None


def _fix_newlines(s: str) -> str:
    parts = s.split('"')
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("\\n", "\n")
    return '"'.join(parts)


def _try_parse(s: str) -> dict | None:
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None


def _parse_sa_json(raw_value: str) -> dict:
    raw = raw_value.strip()
    candidates = [raw]

    for q in ["'", '"']:
        if len(raw) > 2 and raw.startswith(q) and raw.endswith(q):
            candidates.append(raw[1:-1].strip())

    for c in candidates:
        fixed = _fix_newlines(c)
        result = _try_parse(fixed)
        if result:
            return result
        if not fixed.startswith("{"):
            result = _try_parse("{" + fixed + "}")
            if result:
                return result

    raise ValueError(
        f"JSON解析失敗: len={len(raw)}, first30={repr(raw[:30])}"
    )


def _get_service():
    """認証済みの Calendar API サービスオブジェクト（再利用）"""
    global _service_cache
    if _service_cache is not None:
        return _service_cache

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    settings = get_settings()
    if not settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON が未設定です")

    sa_info = _parse_sa_json(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        sa_info, scopes=SCOPES
    )
    _service_cache = build("calendar", "v3", credentials=credentials)
    return _service_cache


def get_today_events() -> list[dict]:
    now_jst = datetime.now(JST)
    start_of_day = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    return _fetch_events(start_of_day.isoformat(), end_of_day.isoformat())


def get_week_events() -> list[dict]:
    now_jst = datetime.now(JST)
    monday = now_jst - timedelta(days=now_jst.weekday())
    start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return _fetch_events(start.isoformat(), end.isoformat())


def get_month_events(year: int, month: int) -> list[dict]:
    import calendar
    first_day = datetime(year, month, 1, tzinfo=JST)
    start_weekday = first_day.weekday()
    cal_start = first_day - timedelta(days=start_weekday)
    _, last_date = calendar.monthrange(year, month)
    last_day = datetime(year, month, last_date, 23, 59, 59, tzinfo=JST)
    end_weekday = last_day.weekday()
    cal_end = last_day + timedelta(days=(6 - end_weekday))
    cal_end = cal_end.replace(hour=23, minute=59, second=59)

    return _fetch_events(cal_start.isoformat(), cal_end.isoformat())


def _fetch_events(time_min: str, time_max: str) -> list[dict]:
    cache_key = f"{time_min}|{time_max}"
    now = time.time()

    # キャッシュチェック
    if cache_key in _cache:
        cached_at, cached_events = _cache[cache_key]
        if now - cached_at < _CACHE_TTL:
            return cached_events

    settings = get_settings()
    service = _get_service()

    result = (
        service.events()
        .list(
            calendarId=settings.GOOGLE_CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=200,
        )
        .execute()
    )

    events = []
    for item in result.get("items", []):
        start = item.get("start", {})
        end = item.get("end", {})
        events.append({
            "id": item.get("id"),
            "summary": item.get("summary", "(無題)"),
            "description": item.get("description", ""),
            "location": item.get("location", ""),
            "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"),
            "all_day": "date" in start and "dateTime" not in start,
            "status": item.get("status", "confirmed"),
        })

    _cache[cache_key] = (now, events)
    return events


def check_connection() -> dict:
    """接続確認（軽量版: 設定チェック + キャッシュ済みデータ優先）"""
    settings = get_settings()
    if not settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        return {"ok": False, "error": "GOOGLE_SERVICE_ACCOUNT_JSON が未設定"}
    if not settings.GOOGLE_CALENDAR_ID:
        return {"ok": False, "error": "GOOGLE_CALENDAR_ID が未設定"}

    # キャッシュにデータがあれば接続済みとみなす
    if _cache:
        return {"ok": True, "event_count": -1}

    try:
        events = get_today_events()
        return {"ok": True, "event_count": len(events)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
