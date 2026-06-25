import asyncio
import os
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

# WHOIS(ポート43)はRender等のクラウドでブロックされスレッドがハングし、
# 分析全体を停止させる原因になる。既定で無効。WHOIS_ENABLED=1 で有効化可。
WHOIS_ENABLED = os.environ.get("WHOIS_ENABLED", "0") == "1"


async def check_domain(url: str) -> dict:
    """ドメイン年齢をWHOISで取得する（既定で無効＝ハング防止）"""
    result = {"domain_age_years": None}
    if not WHOIS_ENABLED:
        return result
    try:
        parsed = urlparse(url)
        domain = parsed.hostname
        if not domain:
            return result
        if domain.startswith("www."):
            domain = domain[4:]

        whois_data = await asyncio.wait_for(
            asyncio.to_thread(_whois_lookup, domain), timeout=8
        )
        if whois_data:
            creation = whois_data.get("creation_date")
            if creation:
                if isinstance(creation, list):
                    creation = min(creation)
                if hasattr(creation, "tzinfo") and creation.tzinfo is None:
                    creation = creation.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                years = (now - creation).days / 365.25
                result["domain_age_years"] = round(years, 1)
    except (Exception, asyncio.TimeoutError):
        pass
    return result


def _whois_lookup(domain: str) -> dict | None:
    # ソケットにハードタイムアウトを付け、スレッドがハングしないようにする
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(6)
    try:
        import whois
        data = whois.whois(domain)
        return {"creation_date": data.creation_date}
    except Exception:
        return None
    finally:
        socket.setdefaulttimeout(old)
