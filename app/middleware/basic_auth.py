"""HTTP Basic Auth ミドルウェア（管理ダッシュボード保護用）

公開すべきエンドポイント（webhook 等）は EXEMPT_PATHS で除外。

**認証情報が未設定のときの挙動（2026-07-20 変更）**
以前は「未設定なら素通し」だったため、本番（Render）で BASIC_AUTH_USER/PASS を
設定し忘れた結果、`/api/leads` が無認証で全公開されていた（商談金額・失注理由・
取引先メールを含む 287 件が誰でも取得できる状態）。
未設定は「まだ設定していない」だけで「公開してよい」ではないので、
**本番では fail-closed**（503 で閉じる）にする。ローカル開発は従来どおり素通し。

- 人間（ダッシュボード）: HTTP Basic 認証
- 機械（ローカルバッチ等）: `X-API-Key` ヘッダ（SALES_API_KEY）
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
    "/favicon.ico",
)

# 本番で認証情報が無いときに閉じる代わりに出すメッセージ
_UNCONFIGURED_MESSAGE = (
    "認証が未設定のため停止しています。"
    "Render の環境変数 BASIC_AUTH_USER / BASIC_AUTH_PASS を設定してください。"
)


def _is_production() -> bool:
    """Render 上で動いているか。Render は RENDER=true を自動で入れる。

    明示的に閉じたい/開けたい場合は SALES_REQUIRE_AUTH=1/0 で上書きできる。
    """
    override = os.environ.get("SALES_REQUIRE_AUTH", "").strip()
    if override:
        return override not in ("0", "false", "False")
    return bool(os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"))


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, exempt_prefixes: Iterable[str] = DEFAULT_EXEMPT_PREFIXES):
        super().__init__(app)
        self.exempt_prefixes = tuple(exempt_prefixes)

    async def dispatch(self, request: Request, call_next):
        user = os.environ.get("BASIC_AUTH_USER", "")
        pw = os.environ.get("BASIC_AUTH_PASS", "")
        api_key = os.environ.get("SALES_API_KEY", "")

        path = request.url.path
        is_exempt = any(path.startswith(prefix) for prefix in self.exempt_prefixes)

        # 認証情報が無い場合:
        #   本番 → 閉じる（fail-closed）。免除パスだけは通す（webhook を落とさないため）
        #   ローカル → 従来どおり素通し
        if not user or not pw:
            if _is_production() and not is_exempt:
                logger.error("BASIC_AUTH_USER/PASS 未設定のためリクエストを拒否: %s", path)
                return Response(
                    status_code=503,
                    content=_UNCONFIGURED_MESSAGE,
                    media_type="text/plain; charset=utf-8",
                )
            return await call_next(request)

        if is_exempt:
            return await call_next(request)

        # 機械クライアント（ローカルバッチ）は API キーで通す
        if api_key:
            got_key = request.headers.get("x-api-key", "")
            if got_key and hmac.compare_digest(got_key, api_key):
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
