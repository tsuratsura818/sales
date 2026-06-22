"""開発プロジェクト基盤ダッシュボード（静的台帳）。

全社プロジェクトの Vercel/Supabase/Render/Shopify リンク・コスト表をまとめた
スタンドアロン HTML。Basic 認証配下のルートとして配信する（Jinja は通さない）。

Credentials タブの機微情報は Git に含めず、サーバー側で注入する:
  - 本番: 環境変数 INFRA_CREDENTIALS_JSON（JSON 文字列）
  - ローカル: リポジトリ直下の infra_credentials.json（.gitignore 済み）
いずれも無ければ Credentials タブは空表示になる。
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["infra"])

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_DASHBOARD_PATH = _BASE_DIR / "app" / "templates" / "infra_dashboard.html"
_CREDS_FILE = _BASE_DIR / "infra_credentials.json"


def _auth_enabled() -> bool:
    """Basic 認証が実際に有効か（未設定なら全公開のため機微情報は出さない）。"""
    return bool(os.environ.get("BASIC_AUTH_USER") and os.environ.get("BASIC_AUTH_PASS"))


def _load_credentials() -> list:
    """機微情報を環境変数 → ローカルファイルの順で読み込む。

    Basic 認証が無効（＝アプリが全公開）の場合は、機微情報を一切返さない。
    本番でクレデンシャルを出すには BASIC_AUTH_USER/PASS の設定が前提。
    """
    # 本番(Render)で認証が無いなら絶対に出さない
    if os.environ.get("RENDER") and not _auth_enabled():
        return []

    raw = os.environ.get("INFRA_CREDENTIALS_JSON", "").strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []
    if _CREDS_FILE.exists():
        try:
            return json.loads(_CREDS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


@router.get("/infra", response_class=HTMLResponse)
async def infra_dashboard():
    """開発プロジェクト基盤ダッシュボード"""
    html = _DASHBOARD_PATH.read_text(encoding="utf-8")
    creds = _load_credentials()
    # </script> でのブレイクアウトを防ぎつつ JSON を埋め込む
    payload = json.dumps(creds, ensure_ascii=False).replace("</", "<\\/")
    inject = f"<script>window.__INFRA_CREDS__ = {payload};</script>"
    html = html.replace("<body>", f"<body>\n{inject}", 1)
    return HTMLResponse(html)
