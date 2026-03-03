import ssl
import socket
from datetime import datetime, timezone
import httpx


async def check_https(url: str, client: httpx.AsyncClient) -> dict:
    """HTTPS対応チェックとSSL証明書残日数を返す"""
    result = {"is_https": None, "ssl_expiry_days": None}

    try:
        # リダイレクトを追跡せず初回レスポンスを確認
        resp = await client.get(url, follow_redirects=False, timeout=10)
        location = resp.headers.get("location", "")

        if url.startswith("https://"):
            result["is_https"] = True
        elif location.startswith("https://"):
            result["is_https"] = True
        else:
            result["is_https"] = False
            return result

        # SSL証明書の有効期限を確認
        from urllib.parse import urlparse
        parsed = urlparse(url if url.startswith("https://") else location)
        hostname = parsed.hostname
        port = parsed.port or 443

        if hostname:
            expiry_days = await _get_ssl_expiry_days(hostname, port)
            result["ssl_expiry_days"] = expiry_days

    except Exception:
        result["is_https"] = False

    return result


async def _get_ssl_expiry_days(hostname: str, port: int) -> int | None:
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        expiry = await loop.run_in_executor(None, _get_cert_expiry, hostname, port)
        if expiry:
            now = datetime.now(timezone.utc)
            delta = expiry - now
            return max(0, delta.days)
    except Exception:
        pass
    return None


def _get_cert_expiry(hostname: str, port: int) -> datetime | None:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                expire_str = cert.get("notAfter", "")
                if expire_str:
                    return datetime.strptime(expire_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return None
