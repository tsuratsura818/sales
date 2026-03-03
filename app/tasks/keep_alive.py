import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

PING_INTERVAL = 600  # 10分


async def keep_alive() -> None:
    """Render無料プランのスリープを防止するself-ping"""
    await asyncio.sleep(30)

    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        logger.info("RENDER_EXTERNAL_URL未設定のため、keep-aliveをスキップ（ローカル環境）")
        return

    health_url = f"{url}/health"
    logger.info(f"keep-alive開始: {health_url} を{PING_INTERVAL // 60}分間隔でping")

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                resp = await client.get(health_url)
                logger.debug(f"keep-alive ping: {resp.status_code}")
            except Exception as e:
                logger.warning(f"keep-alive pingエラー: {e}")

            await asyncio.sleep(PING_INTERVAL)
