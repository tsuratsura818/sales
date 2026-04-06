"""日程調整メール自動生成

Googleカレンダーの空き時間を取得し、候補日時を含むメールを生成
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.lead import Lead

logger = logging.getLogger(__name__)
settings = get_settings()

JST = timezone(timedelta(hours=9))

# 営業時間
BIZ_HOUR_START = 10
BIZ_HOUR_END = 18
# 1スロット = 1時間
SLOT_DURATION_HOURS = 1
# 提案する候補数
MAX_CANDIDATES = 5
# 何日先まで検索するか
SEARCH_DAYS = 14


def _get_busy_times() -> list[tuple[datetime, datetime]]:
    """Googleカレンダーから予定を取得して、busy時間帯を返す"""
    try:
        from app.services.calendar_service import _get_service
        service = _get_service()

        now = datetime.now(JST)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=SEARCH_DAYS)).isoformat()

        result = service.events().list(
            calendarId=settings.GOOGLE_CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        ).execute()

        busy = []
        for item in result.get("items", []):
            start = item.get("start", {})
            end = item.get("end", {})
            s = start.get("dateTime")
            e = end.get("dateTime")
            if s and e:
                busy.append((
                    datetime.fromisoformat(s),
                    datetime.fromisoformat(e),
                ))
        return busy
    except Exception as e:
        logger.warning(f"カレンダー取得エラー（空き時間は推定で生成）: {e}")
        return []


def _is_slot_free(slot_start: datetime, slot_end: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
    """スロットがbusy時間と重ならないか"""
    for bs, be in busy:
        if slot_start < be and slot_end > bs:
            return False
    return True


def get_free_slots(days: int = SEARCH_DAYS, max_slots: int = MAX_CANDIDATES) -> list[dict]:
    """空き時間スロットを取得"""
    busy = _get_busy_times()
    slots = []
    now = datetime.now(JST)
    # 翌営業日から開始
    check_date = now + timedelta(days=1)

    for _ in range(days):
        # 土日スキップ
        if check_date.weekday() >= 5:
            check_date += timedelta(days=1)
            continue

        for hour in range(BIZ_HOUR_START, BIZ_HOUR_END):
            slot_start = check_date.replace(hour=hour, minute=0, second=0, microsecond=0)
            slot_end = slot_start + timedelta(hours=SLOT_DURATION_HOURS)

            if slot_start <= now:
                continue

            if _is_slot_free(slot_start, slot_end, busy):
                slots.append({
                    "start": slot_start.strftime("%Y-%m-%d %H:%M"),
                    "end": slot_end.strftime("%H:%M"),
                    "display": slot_start.strftime("%m/%d(%a) %H:%M") + "〜" + slot_end.strftime("%H:%M"),
                    "date": slot_start.strftime("%Y-%m-%d"),
                    "weekday": ["月", "火", "水", "木", "金", "土", "日"][slot_start.weekday()],
                })

                if len(slots) >= max_slots:
                    return slots

        check_date += timedelta(days=1)

    return slots


def generate_meeting_email(db: Session, lead_id: int) -> dict:
    """日程調整メールを自動生成"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return {"error": "リードが見つかりません"}

    slots = get_free_slots()
    if not slots:
        return {"error": "空き時間が見つかりません"}

    company = lead.title or lead.domain or "御社"
    contact_name = "ご担当者様"

    # 候補日時テキスト
    slot_lines = "\n".join(f"  ・{s['display']}" for s in slots)

    subject = f"【ご面談のお願い】Webサイト改善のご提案 - TSURATSURA"
    body = f"""{contact_name}

お世話になっております。TSURATSURAの西川です。
先日はお返事をいただき、誠にありがとうございます。

{company}のWebサイトについて、具体的なご提案をさせていただきたく、
30分ほどお時間をいただけますと幸いです。

下記の日程で、ご都合のよいお日にちはございますでしょうか。

{slot_lines}

オンライン（Google Meet）またはお電話、いずれの形式でも対応可能です。
上記以外の日程でも調整いたしますので、お気軽にお申し付けください。

何卒よろしくお願いいたします。

───────────────────────
西川
TSURATSURA
"""

    return {
        "subject": subject,
        "body": body,
        "slots": slots,
        "lead_id": lead_id,
        "to": lead.contact_email,
    }
