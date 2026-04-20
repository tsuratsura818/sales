"""音声文字起こしサービス (Gemini 2.5 Flash)

長尺音声対応:
- 10分チャンクに分割→順次Gemini送信→結合
- 入力は UploadFile を受け取り、ストリーミングで /tmp に保存
- 短尺ならチャンクせず直接処理 (高速パス)
"""

import asyncio
import base64
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
from fastapi import UploadFile

from app.config import get_settings


logger = logging.getLogger("transcribe")

MAX_INLINE_SIZE_MB = 18
MIN_TRANSCRIPT_CHARS = 20
MAX_RETRIES = 3
CHUNK_SECONDS = 600              # 10分で分割
LONG_AUDIO_THRESHOLD_SEC = 600   # これ以上ならチャンク処理
FFMPEG_TIMEOUT = 1200             # ffmpeg 最大20分 (長尺も許容)
FFPROBE_TIMEOUT = 60
GEMINI_TIMEOUT = 600

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


# ===== 内部ユーティリティ =====


def _guess_ext(filename: str | None, mime: str | None) -> str:
    if filename:
        ext = Path(filename).suffix.lstrip(".").lower()
        if ext in MIME_TYPES:
            return ext
    if mime:
        m = mime.lower()
        if "webm" in m: return "webm"
        if "ogg" in m or "opus" in m: return "ogg"
        if "mp4" in m or "m4a" in m: return "m4a"
        if "mpeg" in m or "mp3" in m: return "mp3"
        if "wav" in m: return "wav"
    return "webm"


def _check_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise TranscribeError("ffmpeg が見つかりません。サーバーに ffmpeg をインストールしてください。")


def _probe_duration_sync(path: Path) -> float | None:
    """ffprobe で音声長(秒)を取得。失敗時None"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, timeout=FFPROBE_TIMEOUT, text=True,
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning("ffprobe failed: %s", e)
    return None


def _compress_opus_sync(input_path: Path, output_path: Path) -> None:
    """音声を Opus 32kbps / モノラル / 16kHz に圧縮 (単一ファイル)"""
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path),
         "-ac", "1", "-ar", "16000",
         "-c:a", "libopus", "-b:a", "32k",
         str(output_path)],
        capture_output=True, timeout=FFMPEG_TIMEOUT,
    )
    if result.returncode != 0:
        err = result.stderr.decode(errors="replace")[:500]
        raise TranscribeError(f"ffmpeg 圧縮失敗: {err}")


def _split_and_compress_sync(input_path: Path, out_dir: Path, chunk_sec: int) -> list[Path]:
    """1パスで分割+Opus圧縮。チャンクファイル一覧を返す"""
    pattern = str(out_dir / "chunk_%03d.opus")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path),
         "-ac", "1", "-ar", "16000",
         "-c:a", "libopus", "-b:a", "32k",
         "-f", "segment", "-segment_time", str(chunk_sec),
         "-reset_timestamps", "1",
         pattern],
        capture_output=True, timeout=FFMPEG_TIMEOUT,
    )
    if result.returncode != 0:
        err = result.stderr.decode(errors="replace")[:500]
        raise TranscribeError(f"ffmpeg 分割失敗: {err}")
    chunks = sorted(out_dir.glob("chunk_*.opus"))
    if not chunks:
        raise TranscribeError("分割されたチャンクが見つかりません")
    return chunks


async def _stream_upload_to_path(upload: UploadFile, dst: Path, block: int = 1 << 20) -> int:
    """UploadFile を /tmp にストリーミング保存 (メモリ節約)"""
    size = 0
    with open(dst, "wb") as f:
        while True:
            chunk = await upload.read(block)
            if not chunk:
                break
            f.write(chunk)
            size += len(chunk)
    return size


async def _call_gemini(audio_bytes: bytes, mime_type: str, api_key: str, model_name: str) -> str:
    url = API_URL_TEMPLATE.format(model=model_name, key=api_key)
    payload = {
        "contents": [{
            "parts": [
                {"text": TRANSCRIPTION_PROMPT},
                {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio_bytes).decode("utf-8")}},
            ],
        }],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
    }

    async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT) as client:
        last_status = None
        last_body = ""
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(url, json=payload)
            except httpx.TimeoutException:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt * 5)
                    continue
                raise TranscribeError("Gemini API タイムアウト")

            if resp.status_code == 429 and attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt * 15
                logger.info("Gemini 429 retry in %ds (attempt %d)", wait, attempt + 1)
                await asyncio.sleep(wait)
                continue

            last_status = resp.status_code
            last_body = resp.text

            if resp.status_code != 200:
                break

            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                raise TranscribeError(f"Geminiレスポンスが空: {str(data)[:200]}")

            parts = candidates[0].get("content", {}).get("parts", [])
            text = "\n".join(p.get("text", "") for p in parts).strip()
            if not text:
                raise TranscribeError("文字起こし結果が空 (無音の可能性)")
            return text

    if last_status == 429:
        raise TranscribeError("Gemini レート制限。5-10分待って再試行してください")
    raise TranscribeError(f"Gemini API エラー HTTP {last_status}: {last_body[:200]}")


async def _transcribe_file(path: Path, api_key: str, model_name: str) -> str:
    """単一ファイルを読み込んでGeminiに送信"""
    size_mb = path.stat().st_size / 1024 / 1024
    if size_mb > MAX_INLINE_SIZE_MB:
        raise TranscribeError(f"チャンクサイズが{MAX_INLINE_SIZE_MB}MB超 ({size_mb:.1f}MB) — 内部エラー")

    mime_type = MIME_TYPES.get(path.suffix.lstrip("."), "audio/ogg")
    audio_bytes = path.read_bytes()
    return await _call_gemini(audio_bytes, mime_type, api_key, model_name)


# ===== 公開API =====


async def transcribe_upload(
    upload: UploadFile,
    model_key: str = DEFAULT_MODEL,
    chunk_seconds: int = CHUNK_SECONDS,
) -> str:
    """UploadFileをストリーミングで受けて文字起こし。長尺は自動分割。"""
    settings = get_settings()
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise TranscribeError("GEMINI_API_KEY が設定されていません")

    _check_ffmpeg()
    model_name = MODELS.get(model_key, MODELS[DEFAULT_MODEL])

    with tempfile.TemporaryDirectory(prefix="transcribe_") as tmpdir:
        tmp = Path(tmpdir)
        ext = _guess_ext(upload.filename, upload.content_type)
        input_path = tmp / f"input.{ext}"

        size = await _stream_upload_to_path(upload, input_path)
        size_mb = size / 1024 / 1024
        logger.info("upload saved: %s (%.2fMB)", input_path, size_mb)

        duration = await asyncio.to_thread(_probe_duration_sync, input_path)
        logger.info("duration=%s sec", duration)

        # === 短尺パス ===
        if duration is not None and duration < LONG_AUDIO_THRESHOLD_SEC and size_mb <= MAX_INLINE_SIZE_MB:
            logger.info("short path: direct transcribe")
            return await _transcribe_file(input_path, api_key, model_name)

        # === 短め+サイズ超 → 圧縮して1発 ===
        if duration is not None and duration < LONG_AUDIO_THRESHOLD_SEC:
            logger.info("medium path: compress then transcribe")
            compressed = tmp / "compressed.opus"
            await asyncio.to_thread(_compress_opus_sync, input_path, compressed)
            comp_mb = compressed.stat().st_size / 1024 / 1024
            if comp_mb <= MAX_INLINE_SIZE_MB:
                return await _transcribe_file(compressed, api_key, model_name)
            # それでも超えるなら分割フォールバック
            logger.warning("compressed still >%.0fMB, falling back to split", MAX_INLINE_SIZE_MB)
            input_path = compressed

        # === 長尺パス: 分割+圧縮 ===
        logger.info("long path: split into %ds chunks", chunk_seconds)
        chunks_dir = tmp / "chunks"
        chunks_dir.mkdir()
        chunks = await asyncio.to_thread(_split_and_compress_sync, input_path, chunks_dir, chunk_seconds)
        logger.info("%d chunks generated", len(chunks))

        transcripts: list[str] = []
        errors: list[str] = []
        for i, cf in enumerate(chunks, start=1):
            cf_mb = cf.stat().st_size / 1024 / 1024
            logger.info("chunk %d/%d (%.2fMB)", i, len(chunks), cf_mb)
            try:
                if cf_mb > MAX_INLINE_SIZE_MB:
                    raise TranscribeError(f"チャンク{i}が{MAX_INLINE_SIZE_MB}MB超 ({cf_mb:.1f}MB)")
                text = await _transcribe_file(cf, api_key, model_name)
                transcripts.append(text)
            except TranscribeError as e:
                logger.error("chunk %d failed: %s", i, e)
                transcripts.append(f"[チャンク{i}失敗: {e}]")
                errors.append(f"チャンク{i}: {e}")

        if not any(t and not t.startswith("[チャンク") for t in transcripts):
            raise TranscribeError(f"全チャンク失敗: {'; '.join(errors)}")

        # 区切り入れて結合
        parts = []
        for i, t in enumerate(transcripts, start=1):
            parts.append(f"--- Part {i}/{len(chunks)} ---\n{t}")
        return "\n\n".join(parts)


# ===== 後方互換ラッパー =====


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str | None = None,
    content_type: str | None = None,
    model_key: str = DEFAULT_MODEL,
) -> str:
    """後方互換: bytes入力版 (短尺用途のみ想定。長尺は transcribe_upload を使うこと)"""
    settings = get_settings()
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise TranscribeError("GEMINI_API_KEY が設定されていません")

    ext = _guess_ext(filename, content_type)
    mime_type = MIME_TYPES.get(ext, "audio/webm")
    size_mb = len(audio_bytes) / 1024 / 1024
    working_bytes = audio_bytes

    if size_mb > MAX_INLINE_SIZE_MB:
        _check_ffmpeg()
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / f"input.{ext}"
            out_path = Path(tmpdir) / "output.opus"
            in_path.write_bytes(audio_bytes)
            await asyncio.to_thread(_compress_opus_sync, in_path, out_path)
            working_bytes = out_path.read_bytes()
            mime_type = "audio/ogg"
            new_mb = len(working_bytes) / 1024 / 1024
            if new_mb > MAX_INLINE_SIZE_MB:
                raise TranscribeError(
                    f"圧縮後も{MAX_INLINE_SIZE_MB}MB超 ({new_mb:.1f}MB)。transcribe_upload を使ってください"
                )

    model_name = MODELS.get(model_key, MODELS[DEFAULT_MODEL])
    return await _call_gemini(working_bytes, mime_type, api_key, model_name)
