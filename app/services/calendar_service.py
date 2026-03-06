"""Google Calendar API クライアント - サービスアカウント方式"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from app.config import get_settings

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _fix_newlines(s: str) -> str:
    """JSON文字列の外側にある \\n だけ実際の改行に変換する。
    文字列内（private_key等）の \\n はJSON escape として保持。"""
    parts = s.split('"')
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("\\n", "\n")
    return '"'.join(parts)


def _try_parse(s: str) -> dict | None:
    """JSONパースを試みる。失敗時はNone"""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None


def _parse_sa_json(raw_value: str) -> dict:
    """環境変数から読んだサービスアカウントJSONを安全にパースする"""
    raw = raw_value.strip()
    candidates = [raw]

    # 外側クォート除去版を候補に追加
    for q in ["'", '"']:
        if len(raw) > 2 and raw.startswith(q) and raw.endswith(q):
            candidates.append(raw[1:-1].strip())

    # 各候補について: そのまま / {} で囲む の2パターンを試行
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
    """認証済みの Calendar API サービスオブジェクトを返す"""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    settings = get_settings()
    if not settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON が未設定です")

    sa_info = _parse_sa_json(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        sa_info, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=credentials)


def get_today_events() -> list[dict]:
    """当日の予定を取得（JST基準）"""
    now_jst = datetime.now(JST)
    start_of_day = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    return _fetch_events(start_of_day.isoformat(), end_of_day.isoformat())


def get_week_events() -> list[dict]:
    """今週（月曜〜日曜）の予定を取得"""
    now_jst = datetime.now(JST)
    monday = now_jst - timedelta(days=now_jst.weekday())
    start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return _fetch_events(start.isoformat(), end.isoformat())


def _fetch_events(time_min: str, time_max: str) -> list[dict]:
    """Calendar API からイベントを取得し整形して返す"""
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
            maxResults=50,
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

    return events


def check_connection() -> dict:
    """Googleカレンダー接続確認"""
    settings = get_settings()
    if not settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        return {"ok": False, "error": "GOOGLE_SERVICE_ACCOUNT_JSON が未設定"}
    if not settings.GOOGLE_CALENDAR_ID:
        return {"ok": False, "error": "GOOGLE_CALENDAR_ID が未設定"}
    try:
        events = get_today_events()
        return {"ok": True, "event_count": len(events)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def debug_env() -> dict:
    """環境変数のデバッグ情報（秘密情報はマスク）"""
    settings = get_settings()
    raw = settings.GOOGLE_SERVICE_ACCOUNT_JSON or ""
    return {
        "has_json": bool(raw),
        "len": len(raw),
        "first30": repr(raw[:30]),
        "last10": repr(raw[-10:]) if raw else "",
        "calendar_id": settings.GOOGLE_CALENDAR_ID[:20] + "..." if settings.GOOGLE_CALENDAR_ID else "",
    }
