import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SCREENSHOTS_DIR = Path("static/screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _get_paths(lead_id: int) -> dict:
    """スクリーンショットのファイルパスを返す"""
    return {
        "pc": SCREENSHOTS_DIR / f"{lead_id}_pc.png",
        "mobile": SCREENSHOTS_DIR / f"{lead_id}_mobile.png",
    }


def get_screenshot_urls(lead_id: int) -> dict:
    """既存のスクリーンショットURLを返す（なければNone）"""
    paths = _get_paths(lead_id)
    result = {"pc_url": None, "mobile_url": None}
    if paths["pc"].exists():
        result["pc_url"] = f"/static/screenshots/{lead_id}_pc.png"
    if paths["mobile"].exists():
        result["mobile_url"] = f"/static/screenshots/{lead_id}_mobile.png"
    return result


async def capture_screenshots(lead_id: int, url: str) -> dict:
    """スクリーンショット取得（Playwright除去により無効化）"""
    logger.warning(f"スクリーンショット機能はPlaywright除去により無効化されています (lead_id={lead_id})")
    return {"pc_url": None, "mobile_url": None}
