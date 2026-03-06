"""Google Calendar API クライアント - サービスアカウント方式"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from app.config import get_settings

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _parse_sa_json(raw_value: str) -> dict:
    """環境変数から読んだサービスアカウントJSONを安全にパースする"""
    raw = raw_value.strip()

    # 余計なクォートを繰り返し除去
    for q in ["'", '"']:
        if len(raw) > 2 and raw.startswith(q) and raw.endswith(q):
            raw = raw[1:-1]

    # エスケープされた改行を復元（\\n → \n の前に \\\\n → \\n を処理）
    raw = raw.replace("\\\\n", "\x00ESCAPED_NEWLINE\x00")
    raw = raw.replace("\\n", "\n")
    raw = raw.replace("\x00ESCAPED_NEWLINE\x00", "\\n")

    # まず直接パースを試みる
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # JSON部分だけ抽出（プレフィクスやサフィックスがある場合）
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Render環境変数で外側の {} が失われるケースに対応
    if not raw.startswith("{"):
        wrapped = "{" + raw + "}"
        try:
            return json.loads(wrapped)
        except json.JSONDecodeError:
            pass

    raise ValueError(f"JSON解析失敗: len={len(raw)}, first30={repr(raw[:30])}")


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
