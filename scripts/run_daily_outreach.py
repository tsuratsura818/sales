"""日次自動アウトリーチを Mac 常駐（launchd）から1回実行する。

Render 無料プランは10分程度でインスタンスを再起動し、実行中の asyncio タスクを
殺してしまう（uptime 610秒→28秒 の巻き戻りを実測）。毎日20件送るだけの
リードを集めるには10分では足りないため、収集〜送信は常時起動の Mac で回す。

DB は Render と同じ Supabase を見る（.env の DATABASE_URL）。同じ
`app_settings.daily_outreach_last_date` を使うので、Render 側のスケジューラと
二重に走ることはない。

使い方:
    python scripts/run_daily_outreach.py            # その日が未実行なら実行
    python scripts/run_daily_outreach.py --force    # 実行済みでも強制的に実行

launchd（com.tsuratsura.sellbuddy-outreach）から毎日1回呼ばれる。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# リポジトリルートを import パスに入れる（launchd から絶対パスで叩かれるため）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("run_daily_outreach")

JST = timezone(timedelta(hours=9))


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="その日が実行済みでも強制的に実行する")
    parser.add_argument("--ignore-enabled", action="store_true",
                        help="daily_outreach_enabled が OFF でも実行する")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        log.error(
            "DATABASE_URL が未設定です。Render と同じ Supabase を見る必要があります。"
            " .env に DATABASE_URL を設定してください。"
        )
        return 2

    from app.database import init_db, SessionLocal
    from app.models.app_settings import AppSettings
    from app.tasks.daily_outreach_scheduler import run_daily_outreach

    init_db()

    today = datetime.now(JST).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        cfg = db.query(AppSettings).first()
        if not cfg:
            log.error("app_settings が見つかりません")
            return 2
        enabled = getattr(cfg, "daily_outreach_enabled", False)
        last_date = getattr(cfg, "daily_outreach_last_date", None)
        weekdays_only = getattr(cfg, "daily_outreach_weekdays_only", True)
        cap = getattr(cfg, "daily_outreach_daily_cap", 20)
        target_hour = getattr(cfg, "daily_outreach_hour_jst", 10)
    finally:
        db.close()

    # /today のトグルをそのまま尊重する（スマホから止められるようにするため）
    if not enabled and not args.ignore_enabled:
        log.info("daily_outreach_enabled が OFF のため何もしません")
        return 0

    if weekdays_only and datetime.now(JST).weekday() >= 5 and not args.force:
        log.info("土日のため何もしません（平日のみ設定）")
        return 0

    if last_date == today and not args.force:
        log.info(f"本日({today})は実行済みのため何もしません")
        return 0

    # launchd からは定期的に呼ばれるので、設定した時刻を過ぎるまでは待つ
    now_hour = datetime.now(JST).hour
    if now_hour < target_hour and not args.force:
        log.info(f"実行時刻({target_hour}:00 JST)前のため何もしません（現在 {now_hour}時）")
        return 0

    # 先に実行済みを立てる（長い処理中に launchd が重ねて起動しても二重に走らせない）
    db = SessionLocal()
    try:
        cfg = db.query(AppSettings).first()
        cfg.daily_outreach_last_date = today
        db.commit()
    finally:
        db.close()

    log.info(f"日次アウトリーチ開始（上限 {cap}件/日）")
    try:
        result = await run_daily_outreach()
    except Exception:
        log.exception("日次アウトリーチが失敗しました")
        # 失敗した日はやり直せるようにフラグを戻す
        db = SessionLocal()
        try:
            cfg = db.query(AppSettings).first()
            if cfg and cfg.daily_outreach_last_date == today:
                cfg.daily_outreach_last_date = last_date
                db.commit()
        finally:
            db.close()
        return 1

    log.info(f"完了: {result}")

    # 送信ぶんを専用フォルダに振り分ける（返信ぶんは reply_checker が随時拾う）
    try:
        from app.services.mail_folder_service import file_outreach_mail
        filed = file_outreach_mail()
        log.info(f"フォルダ振り分け: 送信{filed['sent']}件 / 返信{filed['replies']}件")
    except Exception as e:
        log.warning(f"フォルダ振り分けに失敗（送信自体は完了しています）: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
