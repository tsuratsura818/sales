"""SellBuddy 秘書チャット用 ローカル Claude ブリッジ。

PC 上で常駐し、ブラウザ(https://sellbuddy.tsuratsura.com)からの依頼を受けて
ローカルにインストール済みの claude(.exe) を実行する。サブスク実行＝API課金なし。

使い方:
    python claude_bridge.py          # 127.0.0.1:3939 で待受
依存なし(標準ライブラリのみ)。ブラウザの localhost アクセスはHTTPSページからも許可される。
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("CLAUDE_BRIDGE_PORT", "3939"))
# トンネル公開時の共有シークレット（設定時は POST /claude で X-Bridge-Secret 必須）
BRIDGE_SECRET = os.environ.get("CLAUDE_BRIDGE_SECRET", "")
CLAUDE_BIN = (
    os.environ.get("CLAUDE_CLI_PATH")
    or shutil.which("claude")
    or ("claude.exe" if platform.system() == "Windows" else "claude")
)
# このオリジンからのアクセスのみ許可(他は echo しない)
ALLOWED_ORIGINS = {
    "https://sellbuddy.tsuratsura.com",
    "https://sales-6g78.onrender.com",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    # Tsumugi（いとをかしマーケ管理）も同じローカルブリッジを利用
    "https://itowocashi-seo-admin.vercel.app",
    "http://localhost:3000",
    # systemプロモート 組織診断（counseling）も同じローカルブリッジを利用
    "https://counseling.systempromote-kitao.com",
    "https://systempromote-counseling.vercel.app",
}


# ── 非同期ジョブ ────────────────────────────────────────────
# Cloudflare のトンネルは1リクエスト100秒で 524 を返すため、Render 等の
# サーバー側から長い生成(バッチ提案文など)を依頼する経路は「投入 → ポーリング」
# の2段構えにする。ブラウザからの短い依頼は従来どおり同期 POST /claude を使う。
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
JOB_TTL_SEC = 1800          # 完了ジョブの保持時間
MAX_JOB_TIMEOUT_SEC = 1800  # 1ジョブあたりの上限


def _sweep_jobs() -> None:
    """TTLを過ぎた完了ジョブを捨てる(メモリ肥大防止)"""
    now = time.time()
    with _JOBS_LOCK:
        stale = [
            jid for jid, j in _JOBS.items()
            if j["status"] != "running" and now - j["finished_at"] > JOB_TTL_SEC
        ]
        for jid in stale:
            del _JOBS[jid]


def _start_job(prompt: str, timeout: int) -> str:
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _JOBS[job_id] = {"status": "running", "result": "", "error": "", "finished_at": 0.0}

    def _work():
        try:
            result = run_claude(prompt, timeout=timeout)
            with _JOBS_LOCK:
                _JOBS[job_id].update(status="done", result=result, finished_at=time.time())
        except Exception as e:
            with _JOBS_LOCK:
                _JOBS[job_id].update(status="error", error=str(e)[:400], finished_at=time.time())

    threading.Thread(target=_work, daemon=True).start()
    _sweep_jobs()
    return job_id


# これらが環境にあると CLI は定額サブスクではなく従量課金のAPIを使ってしまう。
# 課金ゼロを保証するため、実行時に必ず取り除く。
METERED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_URL",
    "ANTHROPIC_BASE_URL",
)


def subscription_env() -> dict:
    env = os.environ.copy()
    for key in METERED_ENV_VARS:
        env.pop(key, None)
    return env


def run_claude(prompt: str, timeout: int = 240) -> str:
    """ローカル claude を実行して出力テキストを返す(okami-wealth と同方式)。"""
    args = [CLAUDE_BIN, "-p", "--output-format", "text"]
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    r = subprocess.run(
        args,
        input=prompt.encode("utf-8"),
        capture_output=True,
        cwd=tempfile.gettempdir(),  # CLAUDE.md 等を読ませない
        timeout=timeout,
        env=subscription_env(),  # 従量課金の指定を持ち込まない
        **kwargs,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[:400] or f"claude exited {r.returncode}")
    return r.stdout.decode("utf-8", "replace").strip()


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get("Origin", "")
        allow = origin if origin in ALLOWED_ORIGINS else "https://sellbuddy.tsuratsura.com"
        self.send_header("Access-Control-Allow-Origin", allow)
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Bridge-Secret")
        # Chrome の Private Network Access 対策（公開HTTPS→localhost を許可）
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "86400")

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _authorized(self) -> bool:
        """トンネル経由で公開される場合はシークレット必須（未設定時はローカル利用として素通し）"""
        return not BRIDGE_SECRET or self.headers.get("X-Bridge-Secret", "") == BRIDGE_SECRET

    def do_GET(self):
        path = self.path.rstrip("/")
        if path in ("/ping", ""):
            self._json(200, {"ok": True, "service": "claude-bridge"})
            return
        # 非同期ジョブの状態取得: GET /claude/job/<job_id>
        if path.startswith("/claude/job/"):
            if not self._authorized():
                self._json(401, {"error": "unauthorized"})
                return
            job_id = path.rsplit("/", 1)[-1]
            with _JOBS_LOCK:
                job = _JOBS.get(job_id)
                payload = dict(job) if job else None
            if not payload:
                self._json(404, {"error": "job not found (expired?)"})
                return
            payload.pop("finished_at", None)
            self._json(200, payload)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.rstrip("/")
        if path not in ("/claude", "/claude/async"):
            self._json(404, {"error": "not found"})
            return
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8", "replace") or "{}")
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                self._json(400, {"error": "prompt is empty"})
                return

            # 非同期: すぐ job_id を返し、生成はバックグラウンドスレッドで走らせる。
            # Cloudflare の100秒制限を受けずに長い生成ができる。
            if path == "/claude/async":
                timeout = int(data.get("timeout") or 240)
                timeout = max(30, min(timeout, MAX_JOB_TIMEOUT_SEC))
                self._json(202, {"job_id": _start_job(prompt, timeout), "status": "running"})
                return

            result = run_claude(prompt)
            self._json(200, {"result": result})
        except subprocess.TimeoutExpired:
            self._json(504, {"error": "claude timeout"})
        except FileNotFoundError:
            self._json(500, {"error": f"claude が見つかりません ({CLAUDE_BIN})"})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def log_message(self, *a):  # 既定の標準エラー出力を抑制
        pass


def main():
    print(f"SellBuddy Claude Bridge → http://127.0.0.1:{PORT}")
    print(f"claude: {CLAUDE_BIN}")
    print("このウィンドウを開いている間だけ秘書チャットが使えます。Ctrl+Cで終了。")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
