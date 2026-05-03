"""
比較ビズ案件 自動応募スクリプト（ローカルPC実行用）

使い方:
    py hikakubiz_watcher.py            # 1回だけ受信トレイをチェックして終了（Task Scheduler用）
    py hikakubiz_watcher.py --watch    # 常駐モード（60秒間隔でポーリング）

事前準備:
    pip install playwright python-dotenv
    playwright install chromium

.env に以下を追加:
    HIKAKUBIZ_USER_ID=kitaoweb
    HIKAKUBIZ_PASSWORD=xxxxx
    （既存の GMAIL_ADDRESS / GMAIL_APP_PASSWORD / LINE_* を流用）
"""
import argparse
import email
import email.header
import imaplib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from playwright.sync_api import Page, TimeoutError as PWTimeoutError, sync_playwright

# ---------- 設定 ----------

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
HB_USER_ID = os.environ.get("HIKAKUBIZ_USER_ID", "")
HB_PASSWORD = os.environ.get("HIKAKUBIZ_PASSWORD", "")
LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

LOGIN_URL = "https://sys.biz.ne.jp/partner/index2.html"
HEARTBEAT_URL = os.environ.get("RENDER_BASE_URL", "https://sales-6g78.onrender.com").rstrip("/") + "/api/heartbeat/hikakubiz_watcher"
DETAILS_URL_RE = re.compile(r"https://sys\.biz\.ne\.jp/partner/inq_lump/details\.html\?tid=(\d+)[^\s\"'<>]*")
TID_LINE_RE = re.compile(r"案件ID[：:]\s*(\d+)")
CATEGORY_RE = re.compile(r"^[▼▽]\s*(.+?)$", re.MULTILINE)

STATE_FILE = ROOT / ".hikakubiz_applied_tids.json"
LOG_FILE = ROOT / ".hikakubiz_log.json"
LOCK_FILE = ROOT / ".hikakubiz_watcher.lock"
LOCK_TTL_SEC = 300  # 5分以上前のロックは古いとみなして無視

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------- 状態管理（多重応募防止） ----------

def load_state() -> set[str]:
    if not STATE_FILE.exists():
        return set()
    try:
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_state(tids: set[str]) -> None:
    STATE_FILE.write_text(json.dumps(sorted(tids)), encoding="utf-8")


def append_log(entry: dict) -> None:
    """応募ログを追記。タイムスタンプ・所要時間・成否・件名を記録"""
    log = []
    if LOG_FILE.exists():
        try:
            log = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            log = []
    log.append(entry)
    LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def load_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


# ---------- Gmail 受信検知 ----------

def fetch_new_hikakubiz_emails() -> list[dict]:
    """info@biz.ne.jp からの未読メールを取得し、tid と詳細URLを抽出"""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        logger.error("GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定")
        return []

    results: list[dict] = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("inbox")

        # 自動転送・手動転送どちらでも拾うため、本文に sys.biz.ne.jp を含む未読を対象にする
        status, data = mail.search(None, '(UNSEEN BODY "sys.biz.ne.jp")')
        if status != "OK" or not data[0]:
            logger.info("新着メールなし")
            mail.logout()
            return []

        for num in data[0].split():
            # PEEK で取得して未読フラグを保持（応募成功時のみ後で既読化する）
            status, msg_data = mail.fetch(num, "(BODY.PEEK[])")
            if status != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            body = _extract_body(msg)

            # tid 抽出
            url_match = DETAILS_URL_RE.search(body)
            if not url_match:
                logger.warning(f"案件URLが見つかりません (uid={num.decode()})")
                continue
            tid = url_match.group(1)

            # 案件ID（任意）
            inq_id_match = TID_LINE_RE.search(body)
            inq_id = inq_id_match.group(1) if inq_id_match else None

            # カテゴリ（任意）
            cat_match = CATEGORY_RE.search(body)
            category = cat_match.group(1).strip() if cat_match else ""

            subject = _decode_subject(msg.get("Subject", ""))
            mail_date_str = msg.get("Date", "")
            mail_received_at = None
            if mail_date_str:
                try:
                    from email.utils import parsedate_to_datetime
                    mail_received_at = parsedate_to_datetime(mail_date_str)
                except Exception:
                    pass

            results.append({
                "uid": num.decode(),
                "tid": tid,
                "inq_id": inq_id,
                "category": category,
                "subject": subject,
                "details_url": url_match.group(0).split("&utm_")[0],
                "mail_received_at": mail_received_at.isoformat() if mail_received_at else None,
            })

        mail.logout()
    except Exception as e:
        logger.error(f"IMAPエラー: {e}")
        return []

    return results


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="ignore")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                html = part.get_payload(decode=True).decode(charset, errors="ignore")
                return re.sub(r"<[^>]+>", " ", html)
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, errors="ignore")
    return ""


def _decode_subject(raw: str) -> str:
    parts = email.header.decode_header(raw)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(text)
    return "".join(out)


# ---------- LINE 通知 ----------

def send_heartbeat(status: str = "ok", message: str = "", count: int | None = None) -> None:
    """Render側に生存通知を送る。失敗してもメイン処理に影響させない"""
    try:
        payload = {"status": status, "message": message[:500]}
        if count is not None:
            payload["count"] = count
        httpx.post(HEARTBEAT_URL, json=payload, timeout=10)
    except Exception as e:
        logger.debug(f"heartbeat送信失敗（無視）: {e}")


def line_notify(text: str) -> None:
    if not LINE_TOKEN or not LINE_USER_ID:
        logger.info(f"[LINE未設定] {text}")
        return
    try:
        resp = httpx.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {LINE_TOKEN}"},
            json={"to": LINE_USER_ID, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"LINE通知失敗: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"LINE通知エラー: {e}")


# ---------- Playwright 自動応募 ----------

def login(page: Page) -> None:
    """比較ビズ出展者管理画面にログイン"""
    page.goto(LOGIN_URL, wait_until="networkidle")
    # ログインフォームは複数フォーム中の最初。input[name=id]/input[name=pass] を使う
    login_form = page.locator("form").first
    login_form.locator("input[name='id']").fill(HB_USER_ID)
    login_form.locator("input[name='pass']").fill(HB_PASSWORD)
    login_form.locator("button[type='submit'][name='Submit']").click()
    page.wait_for_load_state("networkidle")

    # ダッシュボードはログアウトリンク + 出展者ID表示で判定
    has_logout = page.locator("a:has-text('ログアウト'), button:has-text('ログアウト')").count() > 0
    if not has_logout:
        raise RuntimeError(f"ログイン失敗（current url: {page.url}）")
    logger.info(f"ログイン成功 → {page.url}")
    _close_modal(page)


def _close_modal(page: Page) -> None:
    """モーダル（重要なお知らせ等）が出ていれば閉じる。失敗してもエラーにしない"""
    try:
        # 1) Escape で閉じれるモーダルが多い
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass
    try:
        # 2) 残っていれば × ボタン候補をクリック
        for sel in ["button.close", "[aria-label='Close']", ".modal .close", "button:has-text('×')", "button:has-text('閉じる')"]:
            btns = page.query_selector_all(sel)
            for b in btns:
                if b.is_visible():
                    b.click()
                    page.wait_for_timeout(200)
                    break
    except Exception:
        pass


def apply_to_job(page: Page, details_url: str, tid: str) -> tuple[bool, str]:
    """1案件に応募。 (成功フラグ, タイトル) を返す"""
    page.goto(details_url, wait_until="networkidle")
    _close_modal(page)

    # タイトル候補を取得（後でLINE通知に使う）
    title = ""
    for sel in ["h1", "h2", ".inq-title", "[class*='title']"]:
        el = page.query_selector(sel)
        if el:
            t = (el.inner_text() or "").strip()
            if t and len(t) < 200:
                title = t
                break

    # 開始ボタン: 通常は「開封して参加する」、参加枠が埋まった場合は「参加希望申請する」
    # ボタンがページ下部にあるケースもあるのでスクロールしてから検索
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)

    start_clicked = False
    for label in ["開封して参加する", "参加希望申請する"]:
        try:
            loc = page.get_by_role("button", name=re.compile(label))
            if loc.count() > 0:
                loc.first.scroll_into_view_if_needed()
                loc.first.click(timeout=10000)
                start_clicked = True
                logger.info(f"開始ボタン: {label}")
                break
        except Exception:
            pass
        try:
            loc = page.get_by_text(label, exact=False)
            if loc.count() > 0:
                loc.first.scroll_into_view_if_needed()
                loc.first.click(timeout=10000)
                start_clicked = True
                logger.info(f"開始ボタン(text): {label}")
                break
        except Exception:
            pass

    if not start_clicked:
        page.screenshot(path=str(ROOT / f"debug_apply_step1_{tid}.png"), full_page=True)
        raise RuntimeError("開始ボタン (開封して参加する / 参加希望申請する) が見つかりません")

    page.wait_for_load_state("networkidle")
    _close_modal(page)
    # 開始ボタンクリック後の状態を必ずキャプチャしておく
    page.screenshot(path=str(ROOT / f"debug_apply_after_start_{tid}.png"), full_page=True)

    # テンプレートはデフォルト（ヒアリング）のまま、本文も自動挿入されるので待機のみ
    try:
        page.wait_for_selector("textarea", timeout=10000)
    except PWTimeoutError:
        return False, title or f"tid={tid}"

    # 念のためテキストエリアが空でないことを確認
    textarea = page.query_selector("textarea")
    body_value = textarea.input_value() if textarea else ""
    if not body_value or len(body_value.strip()) < 10:
        logger.warning(f"テンプレ本文が挿入されていません (tid={tid})")
        return False, title or f"tid={tid}"

    # 送信ボタン: 「送信して参加する」「送信して申請する」「申請する」など案件状態で文言が変わる
    submit_label = "送信して参加する|送信して申請する|送信して送信|申請する"
    submit_pattern = re.compile(submit_label)
    submit_clicked = False
    try:
        loc = page.get_by_role("button", name=submit_pattern)
        if loc.count() > 0:
            loc.first.scroll_into_view_if_needed()
            loc.first.click(timeout=10000)
            submit_clicked = True
    except Exception:
        pass
    if not submit_clicked:
        try:
            for label in ["送信して参加する", "送信して申請する", "申請する"]:
                loc = page.get_by_text(label, exact=False)
                if loc.count() > 0:
                    loc.first.scroll_into_view_if_needed()
                    loc.first.click(timeout=10000)
                    submit_clicked = True
                    break
        except Exception:
            pass

    if not submit_clicked:
        page.screenshot(path=str(ROOT / f"debug_apply_step2_{tid}.png"), full_page=True)
        raise RuntimeError("送信ボタンが見つかりません")

    page.wait_for_load_state("networkidle")
    _close_modal(page)
    # 成功判定: 送信系ボタンが消えていれば成功
    still_present = page.locator(f"button:has-text('送信して参加する'), button:has-text('送信して申請する'), button:has-text('申請する')").count()
    if still_present > 0:
        page.screenshot(path=str(ROOT / f"debug_apply_step3_{tid}.png"), full_page=True)
        return False, title or f"tid={tid}"

    return True, title or f"tid={tid}"


# ---------- メイン処理 ----------

def process_once() -> None:
    if not HB_USER_ID or not HB_PASSWORD:
        logger.error("HIKAKUBIZ_USER_ID / HIKAKUBIZ_PASSWORD が未設定")
        return

    # 多重起動防止（Task Scheduler が1分間隔で起動してくる前提）
    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < LOCK_TTL_SEC:
            logger.info(f"既に実行中のためスキップ (lock age={int(age)}s)")
            return
        logger.warning(f"古いロック検知 (age={int(age)}s)、削除して続行")

    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    try:
        _process_once_locked()
    finally:
        try:
            LOCK_FILE.unlink()
        except FileNotFoundError:
            pass


def _process_once_locked() -> None:
    emails = fetch_new_hikakubiz_emails()
    # メールゼロでもheartbeatは送る（生存確認のため）
    if not emails:
        send_heartbeat(status="ok_no_mail", message="新着メールなし", count=0)
        return

    applied_tids = load_state()
    targets = [e for e in emails if e["tid"] not in applied_tids]
    if not targets:
        logger.info(f"全{len(emails)}件は既に応募済み")
        send_heartbeat(status="ok_already_applied", message=f"全{len(emails)}件応募済み", count=0)
        return

    logger.info(f"応募対象 {len(targets)}件: {[t['tid'] for t in targets]}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            login(page)
        except Exception as e:
            logger.error(f"ログイン失敗: {e}")
            line_notify(f"⚠️ 比較ビズ ログイン失敗: {e}")
            browser.close()
            return

        for t in targets:
            apply_started = time.time()
            apply_started_dt = datetime.now(timezone.utc).astimezone()
            ok = False
            title = ""
            error = None
            try:
                ok, title = apply_to_job(page, t["details_url"], t["tid"])
            except Exception as e:
                error = str(e)[:300]
                logger.exception(f"応募エラー tid={t['tid']}: {e}")

            applied_at = datetime.now(timezone.utc).astimezone()
            apply_duration = round(time.time() - apply_started, 2)

            mail_received = t.get("mail_received_at")
            mail_to_apply_sec = None
            if mail_received and ok:
                try:
                    received_dt = datetime.fromisoformat(mail_received)
                    mail_to_apply_sec = round((applied_at - received_dt).total_seconds(), 1)
                except Exception:
                    pass

            # ログ追記
            append_log({
                "tid": t["tid"],
                "inq_id": t.get("inq_id"),
                "subject": t.get("subject", ""),
                "category": t.get("category", ""),
                "mail_received_at": mail_received,
                "applied_at": applied_at.isoformat(),
                "apply_duration_sec": apply_duration,
                "mail_to_apply_sec": mail_to_apply_sec,
                "success": ok,
                "error": error,
                "url": t["details_url"],
            })

            if ok:
                applied_tids.add(t["tid"])
                save_state(applied_tids)
                speed_text = (
                    f"\n⏱ メール→応募 {mail_to_apply_sec}秒"
                    if mail_to_apply_sec is not None else ""
                )
                msg = (
                    f"✅ 比較ビズ応募完了\n"
                    f"案件ID: {t.get('inq_id') or t['tid']}\n"
                    f"{t['subject']}\n"
                    f"カテゴリ: {t['category']}{speed_text}\n"
                    f"{t['details_url']}"
                )
                line_notify(msg)
                logger.info(f"応募成功 tid={t['tid']} (mail→apply {mail_to_apply_sec}秒)")
            else:
                err_text = f"\nエラー: {error}" if error else ""
                line_notify(
                    f"⚠️ 比較ビズ応募失敗 (要手動確認)\n"
                    f"tid={t['tid']}{err_text}\n{t['details_url']}"
                )
                logger.warning(f"応募失敗 tid={t['tid']}")

            time.sleep(2)

        browser.close()

    # 全件処理完了後にheartbeat送信
    success_n = sum(1 for tid in [t["tid"] for t in targets] if tid in applied_tids)
    fail_n = len(targets) - success_n
    send_heartbeat(
        status="ok" if fail_n == 0 else "partial_fail",
        message=f"処理{len(targets)}件 成功{success_n} 失敗{fail_n}",
        count=success_n,
    )


def watch_loop(interval_sec: int = 60) -> None:
    logger.info(f"常駐モード開始（{interval_sec}秒間隔）")
    while True:
        try:
            process_once()
        except KeyboardInterrupt:
            logger.info("終了")
            return
        except Exception as e:
            logger.exception(f"ループエラー: {e}")
        time.sleep(interval_sec)


def _summarize_log(entries: list[dict], days: int | None = None) -> dict:
    """ログ集計。daysを指定するとその日数以内に絞る"""
    if days is not None:
        cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=days)
        entries = [
            e for e in entries
            if e.get("applied_at") and datetime.fromisoformat(e["applied_at"]) >= cutoff
        ]
    total = len(entries)
    success = sum(1 for e in entries if e.get("success"))
    fail = total - success
    durations = [e["mail_to_apply_sec"] for e in entries if e.get("mail_to_apply_sec") is not None]
    avg_dur = round(sum(durations) / len(durations), 1) if durations else None
    min_dur = min(durations) if durations else None
    max_dur = max(durations) if durations else None
    return {
        "total": total,
        "success": success,
        "fail": fail,
        "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        "avg_mail_to_apply_sec": avg_dur,
        "min_mail_to_apply_sec": min_dur,
        "max_mail_to_apply_sec": max_dur,
    }


def cmd_stats() -> None:
    """ログを標準出力に表示"""
    log = load_log()
    if not log:
        print("(ログなし)")
        return
    print(f"=== 比較ビズ応募ログ (全 {len(log)} 件) ===")
    print()
    for e in log[-30:]:
        ok = "✅" if e.get("success") else "❌"
        applied = e.get("applied_at", "?")[:19]
        dur = e.get("mail_to_apply_sec")
        dur_text = f"{dur}秒" if dur is not None else "—"
        subject = (e.get("subject") or "")[:50]
        print(f"{ok} {applied}  メール→応募 {dur_text:>8}  {subject}")
    print()
    print("--- サマリー ---")
    for label, days in [("直近7日", 7), ("直近30日", 30), ("全期間", None)]:
        s = _summarize_log(log, days)
        print(
            f"{label}: 応募{s['total']}件 / 成功{s['success']} / 失敗{s['fail']} "
            f"(成功率{s['success_rate']}%) / 平均{s['avg_mail_to_apply_sec']}秒 "
            f"(min={s['min_mail_to_apply_sec']}, max={s['max_mail_to_apply_sec']})"
        )


def cmd_weekly_line() -> None:
    """週次サマリーをLINEに送信（月曜のTask Scheduler想定）"""
    log = load_log()
    week = _summarize_log(log, days=7)
    last4 = _summarize_log(log, days=28)

    if week["total"] == 0:
        msg = "📊 比較ビズ 週次サマリー\n\n直近7日: 応募なし"
    else:
        speed = (
            f"⏱ メール→応募: 平均{week['avg_mail_to_apply_sec']}秒"
            f" / 最速{week['min_mail_to_apply_sec']}秒 / 最遅{week['max_mail_to_apply_sec']}秒"
            if week["avg_mail_to_apply_sec"] is not None else ""
        )
        msg = (
            f"📊 比較ビズ 週次サマリー\n\n"
            f"【直近7日】\n"
            f"応募 {week['total']}件 (成功{week['success']} / 失敗{week['fail']})\n"
            f"成功率 {week['success_rate']}%\n"
            f"{speed}\n\n"
            f"【直近28日】\n"
            f"応募 {last4['total']}件 (成功率 {last4['success_rate']}%)\n"
            f"平均 {last4['avg_mail_to_apply_sec']}秒"
        )
    line_notify(msg)
    print(msg)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="常駐モード")
    parser.add_argument("--interval", type=int, default=60, help="常駐モードのポーリング間隔（秒）")
    parser.add_argument("--stats", action="store_true", help="応募ログサマリーを標準出力")
    parser.add_argument("--weekly-line", action="store_true", help="週次サマリーをLINEに送信")
    args = parser.parse_args()

    if args.stats:
        cmd_stats()
    elif args.weekly_line:
        cmd_weekly_line()
    elif args.watch:
        watch_loop(args.interval)
    else:
        process_once()


if __name__ == "__main__":
    main()
