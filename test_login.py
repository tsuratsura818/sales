"""CW/LCログインテストスクリプト"""
import asyncio
import os
import sys
sys.path.insert(0, ".")

os.makedirs("data/debug_screenshots", exist_ok=True)


async def check_page(label, url, screenshot_name):
    print(f"\n{'=' * 50}")
    print(f"{label} - {url}")
    print("=" * 50)
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            print(f"最終URL: {page.url}")

            inputs = await page.query_selector_all("input")
            print(f"input要素数: {len(inputs)}")
            for inp in inputs:
                n = await inp.get_attribute("name") or ""
                t = await inp.get_attribute("type") or ""
                i = await inp.get_attribute("id") or ""
                ph = await inp.get_attribute("placeholder") or ""
                vis = await inp.is_visible()
                print(f"  name={n}, type={t}, id={i}, placeholder={ph}, visible={vis}")

            path = f"data/debug_screenshots/{screenshot_name}.png"
            await page.screenshot(path=path)
            print(f"スクリーンショット: {path}")
        except Exception as e:
            print(f"エラー: {e}")
        finally:
            await browser.close()


async def main():
    await check_page("CrowdWorks", "https://crowdworks.jp/login", "cw_login")
    await check_page("Lancers", "https://www.lancers.jp/user/login", "lc_login")


if __name__ == "__main__":
    asyncio.run(main())
