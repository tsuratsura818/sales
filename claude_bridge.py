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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("CLAUDE_BRIDGE_PORT", "3939"))
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
}


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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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

    def do_GET(self):
        if self.path.rstrip("/") in ("/ping", ""):
            self._json(200, {"ok": True, "service": "claude-bridge"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/claude":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8", "replace") or "{}")
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                self._json(400, {"error": "prompt is empty"})
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
