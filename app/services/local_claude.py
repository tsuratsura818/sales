"""ローカルの Claude Code サブスクリプションで文章生成を行うラッパー。

Anthropic API(従量課金)は一切使わない。経路は2つ:

1. ローカル実行時: `claude -p` を subprocess で直接呼ぶ
2. Render 等 CLI 不在の環境: Mac に常駐しているブリッジ
   (`claude_bridge.py` + cloudflared トンネル。URLは app_settings.local_bridge_url)
   に HTTP で依頼する

どちらも定額サブスクの枠内で動くため追加課金は発生しない。両方使えない場合は
`is_available()` が False を返すので、呼び出し側で graceful degrade すること。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

import httpx

log = logging.getLogger("local_claude")

CLAUDE_BIN = os.environ.get("CLAUDE_CLI_PATH") or shutil.which("claude") or "claude"

# 1バッチあたりの安全支出上限(USD)。暴走時のセーフティネット
DEFAULT_MAX_BUDGET_USD = float(os.environ.get("CLAUDE_CLI_MAX_BUDGET_USD", "3.0"))

# ブリッジ経由のポーリング間隔
_BRIDGE_POLL_SEC = 5


# CLI に渡すと定額サブスクではなく従量課金のAPIを使ってしまう環境変数。
# .env に ANTHROPIC_API_KEY があると load_dotenv() が os.environ に載せてしまい、
# サブスクではなくAPI課金で動いてしまう（残高があれば黙って課金され続ける）。
_METERED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_URL",
    "ANTHROPIC_BASE_URL",
)


def _subscription_env() -> dict:
    """定額サブスクで動かすための環境を作る（従量課金の指定を取り除く）"""
    env = os.environ.copy()
    for key in _METERED_ENV_VARS:
        env.pop(key, None)
    return env


class ClaudeCliError(RuntimeError):
    """Claude CLI 呼び出しの失敗を示す例外"""


def _cli_available() -> bool:
    """claude CLI が実行可能か軽くチェックする"""
    try:
        r = subprocess.run(
            [CLAUDE_BIN, "--version"],
            capture_output=True, timeout=5, check=False,
            env=_subscription_env(),
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def bridge_endpoint() -> tuple[str, str] | None:
    """Mac 常駐ブリッジの (URL, 共有シークレット)。未登録なら None。

    URL は Mac 側が起動/再接続のたびに /api/bridge/register で更新している。
    """
    try:
        from app.config import get_settings
        from app.database import SessionLocal
        from app.models.app_settings import AppSettings
    except Exception:
        return None

    db = SessionLocal()
    try:
        cfg = db.query(AppSettings).first()
        url = (getattr(cfg, "local_bridge_url", None) or "").rstrip("/") if cfg else ""
    except Exception as e:
        log.debug(f"bridge URL 取得失敗: {e}")
        return None
    finally:
        db.close()

    if not url:
        return None
    return url, (get_settings().BRIDGE_SHARED_SECRET or "")


def _bridge_alive(url: str, secret: str) -> bool:
    try:
        r = httpx.get(f"{url}/ping", headers=_bridge_headers(secret), timeout=8)
        return r.status_code == 200
    except Exception as e:
        log.debug(f"bridge ping 失敗 ({url}): {e}")
        return False


def _bridge_headers(secret: str) -> dict:
    h = {"Content-Type": "application/json"}
    if secret:
        h["X-Bridge-Secret"] = secret
    return h


def is_available() -> bool:
    """ローカルCLI もしくは Mac常駐ブリッジ のどちらかが使えるか"""
    if _cli_available():
        return True
    ep = bridge_endpoint()
    return bool(ep and _bridge_alive(*ep))


async def _invoke_via_bridge(
    user_prompt: str,
    *,
    system_prompt: str | None = None,
    timeout: int = 600,
) -> str:
    """Mac 常駐ブリッジに生成を依頼する(投入 → ポーリング)。

    Cloudflare トンネルは1リクエスト100秒で 524 を返すため、長い生成は
    `POST /claude/async` で job_id を受け取り `GET /claude/job/<id>` を叩いて待つ。
    ブリッジが旧版(非同期未対応)なら同期 `POST /claude` にフォールバックする。
    """
    ep = bridge_endpoint()
    if not ep:
        raise ClaudeCliError(
            "claude CLI が見つからず、Mac常駐ブリッジのURLも未登録です。"
            "Mac側の com.tsuratsura.sellbuddy-bridge が動いているか確認してください。"
        )
    url, secret = ep
    # ブリッジは system prompt を受け取れないので本文に前置きする
    prompt = f"{system_prompt}\n\n---\n\n{user_prompt}" if system_prompt else user_prompt
    headers = _bridge_headers(secret)
    loop = asyncio.get_event_loop()

    def _submit():
        return httpx.post(
            f"{url}/claude/async", headers=headers,
            json={"prompt": prompt, "timeout": timeout}, timeout=30,
        )

    try:
        resp = await loop.run_in_executor(None, _submit)
    except Exception as e:
        raise ClaudeCliError(f"bridge 接続失敗 ({url}): {e}") from e

    if resp.status_code == 404:
        log.info("bridge が非同期未対応(旧版)のため同期呼び出しにフォールバック")
        return await _invoke_via_bridge_sync(prompt, url, headers, timeout)
    if resp.status_code >= 400:
        raise ClaudeCliError(f"bridge submit error {resp.status_code}: {resp.text[:200]}")

    job_id = (resp.json() or {}).get("job_id")
    if not job_id:
        raise ClaudeCliError(f"bridge が job_id を返しませんでした: {resp.text[:200]}")

    def _poll():
        return httpx.get(f"{url}/claude/job/{job_id}", headers=headers, timeout=30)

    deadline = time.monotonic() + timeout + 60
    while time.monotonic() < deadline:
        await asyncio.sleep(_BRIDGE_POLL_SEC)
        try:
            r = await loop.run_in_executor(None, _poll)
        except Exception as e:
            log.debug(f"bridge poll 失敗(継続): {e}")
            continue
        if r.status_code == 404:
            raise ClaudeCliError("bridge job が消えました(ブリッジ再起動?)")
        if r.status_code >= 400:
            raise ClaudeCliError(f"bridge poll error {r.status_code}: {r.text[:200]}")
        body = r.json() or {}
        status = body.get("status")
        if status == "done":
            return body.get("result", "") or ""
        if status == "error":
            raise ClaudeCliError(f"bridge job failed: {body.get('error', '')[:300]}")

    raise ClaudeCliError(f"bridge job timeout after {timeout}s")


async def _invoke_via_bridge_sync(prompt: str, url: str, headers: dict, timeout: int) -> str:
    """旧版ブリッジ向けの同期呼び出し(Cloudflareの100秒制限を受ける)"""
    loop = asyncio.get_event_loop()

    def _post():
        return httpx.post(
            f"{url}/claude", headers=headers, json={"prompt": prompt},
            timeout=min(timeout, 95),
        )

    try:
        r = await loop.run_in_executor(None, _post)
    except Exception as e:
        raise ClaudeCliError(f"bridge 同期呼び出し失敗: {e}") from e
    if r.status_code >= 400:
        raise ClaudeCliError(f"bridge error {r.status_code}: {r.text[:200]}")
    body = r.json() or {}
    if body.get("error"):
        raise ClaudeCliError(f"bridge error: {str(body['error'])[:300]}")
    return body.get("result", "") or ""


async def invoke(
    user_prompt: str,
    *,
    system_prompt: str | None = None,
    timeout: int = 600,
    max_budget_usd: float | None = None,
    model: str | None = None,
) -> str:
    """Claude を headless 実行して生成テキストを返す。

    ローカルに CLI があれば subprocess、無ければ Mac 常駐ブリッジ経由。

    - tools はすべて無効化(生成のみ)
    - session 永続化は行わない
    - 権限プロンプトはスキップ
    """
    if not _cli_available():
        return await _invoke_via_bridge(user_prompt, system_prompt=system_prompt, timeout=timeout)

    args: list[str] = [
        CLAUDE_BIN,
        "-p", user_prompt,
        "--output-format", "json",
        "--tools", "",
        "--no-session-persistence",
        "--permission-mode", "dontAsk",
        "--max-budget-usd", str(max_budget_usd if max_budget_usd is not None else DEFAULT_MAX_BUDGET_USD),
        "--disable-slash-commands",
    ]
    if system_prompt:
        args += ["--system-prompt", system_prompt]
    if model:
        args += ["--model", model]

    log.debug("invoke claude cli: budget=%s, prompt_len=%d", args[args.index('--max-budget-usd')+1], len(user_prompt))

    # Windows + uvicorn の SelectorEventLoop だと asyncio.create_subprocess_exec が
    # NotImplementedError(空メッセージ) を投げて使えないため、blocking subprocess.run を
    # thread executor で実行する。プラットフォーム共通で安定。
    def _run_blocking() -> tuple[int, bytes, bytes]:
        try:
            r = subprocess.run(
                args,
                capture_output=True,
                timeout=timeout,
                check=False,
                env=_subscription_env(),
                cwd=tempfile.gettempdir(),  # CLAUDE.md 等を読ませない
            )
            return r.returncode, r.stdout or b"", r.stderr or b""
        except FileNotFoundError as e:
            raise ClaudeCliError(
                f"claude CLI が見つかりません ({CLAUDE_BIN})。ローカル環境で実行してください。"
            ) from e
        except subprocess.TimeoutExpired:
            raise ClaudeCliError(f"claude CLI timeout after {timeout}s")

    loop = asyncio.get_event_loop()
    returncode, stdout_b, stderr_b = await loop.run_in_executor(None, _run_blocking)

    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")

    # 失敗理由は stderr ではなく stdout の JSON に入ることがある
    # （例: 利用上限に当たると exit 1 + stdout に "Credit balance is too low"、stderr は空）。
    # stderr だけ見ていると「claude CLI exit 1: 」と理由が空のまま延々リトライしてしまう。
    detail = ""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        envelope = None
    else:
        if envelope.get("is_error") or returncode != 0:
            detail = str(envelope.get("result", ""))[:300]

    if returncode != 0:
        reason = detail or stderr[:400] or stdout[:200] or "(理由なし)"
        raise _classify_error(f"claude CLI exit {returncode}: {reason}", reason)

    if envelope is None:
        raise ClaudeCliError(f"claude CLI stdout is not JSON: {stdout[:200]}")

    if envelope.get("is_error"):
        raise _classify_error(f"claude returned error: {detail}", detail)

    return envelope.get("result", "") or ""


# サブスクの利用上限に当たったことを示す文言。これが出たら課金経路には
# 一切フォールバックせず、処理を止めて時間を空ける。
_QUOTA_MARKERS = (
    "credit balance is too low",
    "hit your limit",       # 例: "You've hit your limit · resets 1pm (Asia/Tokyo)"
    "limit reached",
    "usage limit",
    "rate limit",
    "quota",
    "too many requests",
)


class ClaudeQuotaError(ClaudeCliError):
    """サブスクの利用上限に到達したことを示す"""


def _classify_error(message: str, reason: str) -> ClaudeCliError:
    low = (reason or "").lower()
    if any(marker in low for marker in _QUOTA_MARKERS):
        return ClaudeQuotaError(message)
    return ClaudeCliError(message)


def _loads_lenient(s: str) -> Any:
    """JSON文字列内に生の改行が入っていても読めるようにパースする。

    営業メールの本文は段落分けのため改行を含む。生成側が改行を \\n に
    エスケープせず素の改行のまま返すことがあり、その場合 json.loads は
    "Invalid control character" で失敗する（ChatGPT の応答で実測）。
    strict=False は文字列リテラル内の制御文字を許容する。
    """
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return json.loads(s, strict=False)


def extract_json(text: str) -> Any:
    """Claude の自然文レスポンスから最初の JSON ブロックを抽出してパース。

    - ``` json ... ``` のコードブロック優先
    - 次に最初の { または [ から対応する終端まで
    """
    if not text:
        raise ClaudeCliError("empty response")

    # ```json ... ``` / ``` ... ```
    import re
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        candidate = fence.group(1).strip()
        try:
            return _loads_lenient(candidate)
        except json.JSONDecodeError:
            pass

    # 最初の { / [ から対応終端までを貪欲に探索
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i >= 0),
        default=-1,
    )
    if start < 0:
        raise ClaudeCliError(f"no JSON found in response: {text[:200]}")

    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                candidate = text[start:i+1]
                try:
                    return _loads_lenient(candidate)
                except json.JSONDecodeError as e:
                    raise ClaudeCliError(f"json parse failed: {e}") from e

    raise ClaudeCliError(f"unterminated JSON in response: {text[:200]}")
