import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse


async def check_domain(url: str) -> dict:
    """ドメイン年齢をWHOISで取得する"""
    result = {"domain_age_years": None}
    try:
        parsed = urlparse(url)
        domain = parsed.hostname
        if not domain:
            return result

        # www. を除去
        if domain.startswith("www."):
            domain = domain[4:]

        whois_data = await asyncio.wait_for(
            asyncio.to_thread(_whois_lookup, domain), timeout=10
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
    try:
        import whois
        data = whois.whois(domain)
        return {"creation_date": data.creation_date}
    except Exception:
        return None
