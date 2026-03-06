import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.monitor_settings import MonitorSettings

logger = logging.getLogger(__name__)
_config = get_settings()

DEFAULT_CW_CATEGORIES = [6, 7, 28]
DEFAULT_LC_CATEGORIES = [80, 90, 100]


class MonitorSettingsData:
    """設定値のデータクラス（DBレコードがない場合のフォールバック含む）"""
    def __init__(
        self,
        match_threshold: int = 70,
        monitor_interval_minutes: int = 120,
        user_profile_text: str = "",
        cw_categories: list[int] | None = None,
        lc_categories: list[int] | None = None,
        evaluate_system_prompt: str = "",
    ):
        self.match_threshold = match_threshold
        self.monitor_interval_minutes = monitor_interval_minutes
        self.user_profile_text = user_profile_text
        self.cw_categories = cw_categories or DEFAULT_CW_CATEGORIES
        self.lc_categories = lc_categories or DEFAULT_LC_CATEGORIES
        self.evaluate_system_prompt = evaluate_system_prompt


def get_monitor_settings(db: Optional[Session] = None) -> MonitorSettingsData:
    """DBから設定を取得。レコードがなければconfig.pyのデフォルト値を使用。"""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        row = db.query(MonitorSettings).first()
        if not row:
            return MonitorSettingsData(
                match_threshold=_config.JOB_MATCH_THRESHOLD,
                monitor_interval_minutes=_config.JOB_MONITOR_INTERVAL_MINUTES,
                user_profile_text=_config.USER_PROFILE_TEXT,
            )

        cw_cats = DEFAULT_CW_CATEGORIES
        lc_cats = DEFAULT_LC_CATEGORIES
        if row.search_categories:
            try:
                cats = json.loads(row.search_categories)
                cw_cats = cats.get("crowdworks", DEFAULT_CW_CATEGORIES)
                lc_cats = cats.get("lancers", DEFAULT_LC_CATEGORIES)
            except (json.JSONDecodeError, TypeError):
                pass

        return MonitorSettingsData(
            match_threshold=row.match_threshold,
            monitor_interval_minutes=row.monitor_interval_minutes,
            user_profile_text=row.user_profile_text or "",
            cw_categories=cw_cats,
            lc_categories=lc_cats,
            evaluate_system_prompt=row.evaluate_system_prompt or "",
        )
    except Exception as e:
        logger.error(f"設定取得エラー: {e}")
        return MonitorSettingsData(
            match_threshold=_config.JOB_MATCH_THRESHOLD,
            monitor_interval_minutes=_config.JOB_MONITOR_INTERVAL_MINUTES,
            user_profile_text=_config.USER_PROFILE_TEXT,
        )
    finally:
        if close_db:
            db.close()
