"""音声文字起こしサービス (Gemini 2.5 Flash)

minutes-cc-v2 のロジックをWebアプリ向けに移植。
- bytes入力 (ブラウザ録音のアップロードを想定)
- 18MB超は ffmpeg で Opus 圧縮
- 429時の指数バックオフリトライ
- 機密データはGoogle AI学習に利用される点に注意 (無料枠の規約)
"""

import asyncio
import base64
import subprocess
import tempfile
from pathlib import Path

import httpx

from app.config import get_settings


MAX_INLINE_SIZE_MB = 18
MIN_TRANSCRIPT_CHARS = 20
MAX_RETRIES = 3

MODELS = {
    "flash": "gemini-2.5-flash",
    "flash-lite": "gemini-2.5-flash-lite",
    "pro": "gemini-2.5-pro",
}
DEFAULT_MODEL = "flash"

API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
)

MIME_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mp3",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "flac": "audio/flac",
    "webm": "audio/webm",
}

TRANSCRIPTION_PROMPT = """この音声を日本語で文字起こしをしてください。

# ルール
- 話者が複数いる場合は「話者A:」「話者B:」のように区別する
- フィラー (「えーと」「あのー」「まあ」「そうですね」等) は自然に整理する
- タイムスタンプは不要
- 聞き取れない部分は [不明瞭] と記載
- 固有名詞・専門用語は正確に書き起こす
- 特にTSURATSURA関連用語は正確に:
  いとをかしTsumugi, Komapara, WOLFGANG, 旅狼, Pivolink, PRESSLAB,
  BannerForge Pro, オオカミの森, おくり狼のアオン, TAP TO BREW, フローリア大阪

# 出力形式
文字起こし本文のみを出力する。前置き・注釈・メタコメントは一切入れない。"""


class TranscribeError(Exception):
    pass


def _guess_ext(filename: str | None, mime: str | None) -> str:
    if filename:
        ext = Path(filename).suffix.lstrip(".").lower()
        if ext in MIME_TYPES:
            return ext
    if mime:
        m = mime.lower()
        if "webm" in m:
            return "webm"
        if "ogg" in m or "opus" in m:
            return "ogg"
        if "mp4" in m or "m4a" in m:
            return "m4a"
        if "mpeg" in m or "mp3" in m:
            return "mp3"
        if "wav" in m:
            return "wav"
    return "webm"


def _compress_audio_sync(input_path: Path, output_path: Path) -> bool:
    """ffmpeg で Opus 32kbps / モノラル / 16kHz に圧縮"""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(input_path),
                "-ac", "1", "-ar", "16000",
                "-c:a", "libopus", "-b:a", "32k",
                str(output_path),
            ],
            capture_output=True, timeout=300,
        )
        return result.returncode == 0
    except FileNotFoundError:
        raise TranscribeError("ffmpeg が見つかりません。サーバーに ffmpeg をインストールしてください。")
    except subprocess.TimeoutExpired:
        raise TranscribeError("音声圧縮がタイムアウトしました。")


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str | None = None,
    content_type: str | None = None,
    model_key: str = DEFAULT_MODEL,
) -> str:
    """音声バイト列を文字起こし。失敗時は TranscribeError を投げる。"""
    settings = get_settings()
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise TranscribeError("GEMINI_API_KEY が設定されていません。")

    ext = _guess_ext(filename, content_type)
    mime_type = MIME_TYPES.get(ext, "audio/webm")

    # 18MB超なら ffmpeg で圧縮 (tempfile経由で非同期実行)
    size_mb = len(audio_bytes) / 1024 / 1024
    working_bytes = audio_bytes

    if size_mb > MAX_INLINE_SIZE_MB:
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / f"input.{ext}"
            out_path = Path(tmpdir) / "output.opus"
            in_path.write_bytes(audio_bytes)

            ok = await asyncio.to_thread(_compress_audio_sync, in_path, out_path)
            if not ok:
                raise TranscribeError("ffmpeg での音声圧縮に失敗しました。")

            working_bytes = out_path.read_bytes()
            mime_type = "audio/ogg"
            new_size_mb = len(working_bytes) / 1024 / 1024
            if new_size_mb > MAX_INLINE_SIZE_MB:
                raise TranscribeError(
                    f"圧縮後も{MAX_INLINE_SIZE_MB}MB超 ({new_size_mb:.1f}MB)。音声を分割してください。"
                )

    model_name = MODELS.get(model_key, MODELS[DEFAULT_MODEL])
    url = API_URL_TEMPLATE.format(model=model_name, key=api_key)

    audio_b64 = base64.b64encode(working_bytes).decode("utf-8")
    payload = {
        "contents": [{
            "parts": [
                {"text": TRANSCRIPTION_PROMPT},
                {"inline_data": {"mime_type": mime_type, "data": audio_b64}},
            ],
        }],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
    }

    # 指数バックオフリトライ
    last_status = None
    last_body = ""
    async with httpx.AsyncClient(timeout=600) as client:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(url, json=payload)
            except httpx.TimeoutException:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt * 5)
                    continue
                raise TranscribeError("Gemini API がタイムアウトしました。")

            if resp.status_code == 429 and attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt * 15)
                continue

            last_status = resp.status_code
            last_body = resp.text

            if resp.status_code != 200:
                break

            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                raise TranscribeError(f"Geminiからの応答が空: {data}")

            parts = candidates[0].get("content", {}).get("parts", [])
            text = "\n".join(p.get("text", "") for p in parts).strip()

            if not text:
                raise TranscribeError("文字起こし結果が空でした (無音の可能性)。")

            return text

    if last_status == 429:
        raise TranscribeError("Gemini API レート制限に達しました。5-10分待って再試行してください。")
    raise TranscribeError(f"Gemini API エラー (HTTP {last_status}): {last_body[:300]}")
