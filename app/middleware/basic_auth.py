"""HTTP Basic Auth ミドルウェア（管理ダッシュボード保護用）

公開すべきエンドポイント（webhook 等）は EXEMPT_PATHS で除外。
環境変数 BASIC_AUTH_USER / BASIC_AUTH_PASS が未設定なら認証スキップ（dev用）。
"""
import base64
import hmac
import logging
import os
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# 認証を求めない公開パス
DEFAULT_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/webhook/line",          # LINE webhook（署名検証あり）
    "/api/webhook/inbound",   # 外部webhook（X-Webhook-Secret検証あり）
    "/track/",                # 開封/クリック追跡（トークンで保護）
    "/api/heartbeat/",        # ローカルバッチからの生存通知（ネット越し）
    "/static/",               # 静的アセット（必要なら個別保護）
    "/health",
    "/docs",                  # Swagger（必要なら閉じる）
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, exempt_prefixes: Iterable[str] = DEFAULT_EXEMPT_PREFIXES):
        super().__init__(app)
        self.exempt_prefixes = tuple(exempt_prefixes)

    async def dispatch(self, request: Request, call_next):
        user = os.environ.get("BASIC_AUTH_USER", "")
        pw = os.environ.get("BASIC_AUTH_PASS", "")

        # 認証情報未設定時は素通し（開発・初期セットアップ用）
        if not user or not pw:
            return await call_next(request)

        path = request.url.path
        for prefix in self.exempt_prefixes:
            if path.startswith(prefix):
                return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Basic "):
            try:
                raw = base64.b64decode(auth_header[6:]).decode("utf-8", "ignore")
                got_user, _, got_pw = raw.partition(":")
                if hmac.compare_digest(got_user, user) and hmac.compare_digest(got_pw, pw):
                    return await call_next(request)
            except Exception:
                pass

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="SellBuddy"'},
            content="認証が必要です",
            media_type="text/plain; charset=utf-8",
        )
