"""半自動応募ヘルパー（ローカルPC常駐）

LINEで「🚀 応募ページを開く」を押すと:
- Render側でステータスが open_requested に変わる
- このスクリプトが10秒間隔でキューを取得
- 該当案件のURLをデフォルトブラウザで開く
- 提案文をクリップボードにコピー（応募フォームで Ctrl+V でペースト可）
- Render側に opened ステータスを返却

事前準備:
    pip install pyperclip httpx python-dotenv

使い方:
    py apply_helper.py            # 常駐モード（10秒間隔ポーリング）
    py apply_helper.py --once     # 1回だけチェック
"""
import argparse
import logging
import os
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pyperclip
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

SERVER_URL = os.environ.get("RENDER_BASE_URL", "https://sales-6g78.onrender.com").rstrip("/")
QUEUE_URL = f"{SERVER_URL}/api/jobs/open-queue"
MARK_OPENED_URL = f"{SERVER_URL}/api/jobs/{{}}/mark-opened"
HEARTBEAT_URL = f"{SERVER_URL}/api/heartbeat/apply_helper"
POLL_INTERVAL = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("apply_helper")


def send_heartbeat(status="ok", message="", count=None):
    try:
        payload = {"status": status, "message": message[:500]}
        if count is not None:
            payload["count"] = int(count)
        httpx.post(HEARTBEAT_URL, json=payload, timeout=10)
    except Exception:
        pass


def fetch_queue():
    try:
        r = httpx.get(QUEUE_URL, timeout=15, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"queue fetch error: {e}")
        return []


def mark_opened(job_id: int):
    try:
        httpx.post(MARK_OPENED_URL.format(job_id), timeout=10, follow_redirects=True)
    except Exception as e:
        logger.warning(f"mark-opened error (job_id={job_id}): {e}")


def open_application(job: dict) -> bool:
    """ブラウザを開いて提案文をクリップボードへ"""
    url = job.get("url", "")
    proposal = job.get("proposal_text", "") or ""
    title = job.get("title", "")
    if not url:
        logger.error(f"job_id={job.get('id')} に URL なし")
        return False

    # 1. クリップボードにコピー
    try:
        pyperclip.copy(proposal)
        logger.info(f"📋 提案文をクリップボードへコピー ({len(proposal)}文字)")
    except Exception as e:
        logger.error(f"clipboard error: {e}")

    # 2. デフォルトブラウザで案件URLを開く
    try:
        webbrowser.open(url, new=2)  # new=2 = 新タブ
        logger.info(f"🌐 ブラウザ起動: {url}")
        logger.info(f"   案件: {title[:60]}")
    except Exception as e:
        logger.error(f"browser open error: {e}")
        return False

    return True


def process_once() -> int:
    """1回だけキューを処理。処理した件数を返す"""
    queue = fetch_queue()
    if not queue:
        return 0

    logger.info(f"📥 キュー件数: {len(queue)}件")
    processed = 0
    for job in queue:
        if open_application(job):
            mark_opened(job["id"])
            processed += 1
            time.sleep(2)  # 連続オープンを避ける

    return processed


def watch_loop():
    logger.info(f"🚀 apply_helper 常駐モード開始 (poll {POLL_INTERVAL}s)")
    logger.info(f"   サーバー: {SERVER_URL}")
    last_heartbeat = 0
    while True:
        try:
            n = process_once()
            now = time.time()
            # 5分ごとに heartbeat
            if now - last_heartbeat > 300:
                send_heartbeat(status="ok", message=f"running, processed +{n}", count=n)
                last_heartbeat = now
        except KeyboardInterrupt:
            logger.info("終了")
            return
        except Exception as e:
            logger.exception(f"loop error: {e}")
        time.sleep(POLL_INTERVAL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="1回だけ実行して終了")
    args = parser.parse_args()
    if args.once:
        n = process_once()
        print(f"処理: {n}件")
    else:
        watch_loop()


if __name__ == "__main__":
    main()
