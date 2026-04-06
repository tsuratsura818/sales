from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    SERPAPI_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    PAGESPEED_API_KEY: str = ""
    DATABASE_URL: str = "sqlite:///./sales.db"
    MAX_CONCURRENT_ANALYSIS: int = 5
    ANALYSIS_TIMEOUT_SEC: int = 15
    CLAUDE_MODEL: str = "claude-opus-4-6"
    CLAUDE_MODEL_EVAL: str = "claude-haiku-4-5-20251001"
    CLAUDE_MODEL_PROPOSAL: str = "claude-sonnet-4-6"
    OUTLOOK_FROM_ADDRESS: str = ""
    GMAIL_ADDRESS: str = ""
    GMAIL_APP_PASSWORD: str = ""

    # LINE Messaging API
    LINE_CHANNEL_ACCESS_TOKEN: str = ""
    LINE_CHANNEL_SECRET: str = ""
    LINE_USER_ID: str = ""

    # クラウドソーシング認証
    CROWDWORKS_EMAIL: str = ""
    CROWDWORKS_PASSWORD: str = ""
    LANCERS_EMAIL: str = ""
    LANCERS_PASSWORD: str = ""

    # 案件モニター設定
    JOB_MONITOR_INTERVAL_MINUTES: int = 30
    JOB_MATCH_THRESHOLD: int = 70
    USER_PROFILE_TEXT: str = ""

    # Notion連携（案件管理）
    NOTION_API_KEY: str = ""
    NOTION_PROJECT_DB_ID: str = ""
    NOTION_TASK_DB_ID: str = ""

    # Googleカレンダー連携
    GOOGLE_SERVICE_ACCOUNT_JSON: str = ""
    GOOGLE_CALENDAR_ID: str = ""

    # 1日のタスク自動立案
    DAILY_PLAN_HOUR_JST: int = 8
    DAILY_PLAN_ENABLED: bool = True

    # Render
    RENDER_BASE_URL: str = "https://sellbuddy.tsuratsura.com"

    # 返信検知
    REPLY_CHECK_INTERVAL_SEC: int = 300

    # Webhook
    WEBHOOK_SECRET: str = ""

    # 週次レポート
    WEEKLY_REPORT_DAY: int = 0  # 0=月曜
    WEEKLY_REPORT_HOUR_JST: int = 9

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
