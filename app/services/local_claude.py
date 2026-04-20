"""ローカルの Claude Code CLI (`claude -p`) を subprocess で呼び出すラッパー。

Anthropic API を直接叩かず、ユーザーのローカル Claude Code 認証を利用して
文章生成を行う。Render等の本番環境では CLI が存在しないため、
`is_available()` で事前チェックして呼び出し側で graceful degrade すること。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from typing import Any

log = logging.getLogger("local_claude")

CLAUDE_BIN = os.environ.get("CLAUDE_CLI_PATH") or shutil.which("claude") or "claude"

# 1バッチあたりの安全支出上限(USD)。暴走時のセーフティネット
DEFAULT_MAX_BUDGET_USD = float(os.environ.get("CLAUDE_CLI_MAX_BUDGET_USD", "3.0"))


class ClaudeCliError(RuntimeError):
    """Claude CLI 呼び出しの失敗を示す例外"""


def is_available() -> bool:
    """claude CLI が実行可能か軽くチェックする(本番環境判定用)"""
    try:
        r = subprocess.run(
            [CLAUDE_BIN, "--version"],
            capture_output=True, timeout=5, check=False,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


async def invoke(
    user_prompt: str,
    *,
    system_prompt: str | None = None,
    timeout: int = 600,
    max_budget_usd: float | None = None,
    model: str | None = None,
) -> str:
    """Claude CLI を headless 実行して `result` フィールドの文字列を返す。

    - tools はすべて無効化(生成のみ)
    - session 永続化は行わない
    - 権限プロンプトはスキップ
    """
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

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise ClaudeCliError(
            f"claude CLI が見つかりません ({CLAUDE_BIN})。ローカル環境で実行してください。"
        ) from e

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        try:
            await proc.communicate()
        except Exception:
            pass
        raise ClaudeCliError(f"claude CLI timeout after {timeout}s")

    if proc.returncode != 0:
        err = (stderr_b or b"").decode("utf-8", errors="replace")[:400]
        raise ClaudeCliError(f"claude CLI exit {proc.returncode}: {err}")

    stdout = (stdout_b or b"").decode("utf-8", errors="replace")
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise ClaudeCliError(f"claude CLI stdout is not JSON: {stdout[:200]}") from e

    if envelope.get("is_error"):
        raise ClaudeCliError(f"claude returned error: {envelope.get('result', '')[:300]}")

    return envelope.get("result", "") or ""


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
            return json.loads(candidate)
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
                    return json.loads(candidate)
                except json.JSONDecodeError as e:
                    raise ClaudeCliError(f"json parse failed: {e}") from e

    raise ClaudeCliError(f"unterminated JSON in response: {text[:200]}")
