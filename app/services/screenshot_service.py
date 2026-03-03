import asyncio
import os
from pathlib import Path

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
    """PlaywrightでPC版・スマホ版のスクリーンショットを取得する"""
    paths = _get_paths(lead_id)
    result = {"pc_url": None, "mobile_url": None}

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            try:
                # PC版 (1280x800)
                pc_page = await browser.new_page(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                await pc_page.goto(url, wait_until="networkidle", timeout=20000)
                await pc_page.screenshot(
                    path=str(paths["pc"]),
                    full_page=False,
                    type="png",
                )
                result["pc_url"] = f"/static/screenshots/{lead_id}_pc.png"
                await pc_page.close()

                # スマホ版 (375x667 - iPhone SE相当)
                mobile_page = await browser.new_page(
                    viewport={"width": 375, "height": 667},
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
                    is_mobile=True,
                )
                await mobile_page.goto(url, wait_until="networkidle", timeout=20000)
                await mobile_page.screenshot(
                    path=str(paths["mobile"]),
                    full_page=False,
                    type="png",
                )
                result["mobile_url"] = f"/static/screenshots/{lead_id}_mobile.png"
                await mobile_page.close()

            finally:
                await browser.close()

    except Exception as e:
        # スクリーンショット失敗は致命的ではないのでログだけ
        print(f"Screenshot error for lead {lead_id}: {e}")

    return result
