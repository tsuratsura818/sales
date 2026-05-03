"""ローカル実行バッチ（比較ビズ・Lancers）のheartbeat監視

毎日10:35 JSTに比較ビズのheartbeatを確認、60分以内に届いていなければ
LINE通知（PCシャットダウン・スケジューラ無効化等を検知）
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models.heartbeat import Heartbeat
from app.services.line_service import push_text_message

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))

# 名前 → 最終heartbeatからの最大許容秒
WATCHED = {
    "hikakubiz_watcher": {
        "max_age_sec": 90 * 60,  # 1.5時間以内に1度はheartbeatされるべき（10:00-10:30実行＋余裕）
        "alert_hour_jst": 11,  # 11時台に1回だけアラート
        "alert_label": "比較ビズ自動応募",
    },
    "lancers_local": {
        "max_age_sec": 90 * 60,
        "alert_hour_jst": 12,
        "alert_label": "Lancers取得",
    },
}

# 1日に1回だけアラートするためのフラグ（メモリ）
_alerted_today: dict[str, str] = {}


async def heartbeat_checker():
    logger.info("Heartbeatチェッカー開始")
    await asyncio.sleep(60)

    while True:
        try:
            now_jst = datetime.now(JST)
            today_key = now_jst.strftime("%Y-%m-%d")

            for name, cfg in WATCHED.items():
                # アラート時刻帯のみチェック
                if now_jst.hour != cfg["alert_hour_jst"]:
                    continue
                # 1日1回まで
                if _alerted_today.get(name) == today_key:
                    continue

                db = SessionLocal()
                try:
                    row = db.query(Heartbeat).filter(Heartbeat.name == name).first()
                    if not row or not row.last_at:
                        msg = (
                            f"⚠️ {cfg['alert_label']} の生存確認失敗\n"
                            f"heartbeatが一度も届いていません。\n"
                            f"PCの起動・Task Schedulerの稼働を確認してください。"
                        )
                        await push_text_message(msg)
                        _alerted_today[name] = today_key
                        logger.warning(f"heartbeat未到達: {name}")
                        continue

                    age = (datetime.now() - row.last_at).total_seconds()
                    if age > cfg["max_age_sec"]:
                        msg = (
                            f"⚠️ {cfg['alert_label']} の生存確認失敗\n"
                            f"最終生存: {row.last_at.strftime('%Y-%m-%d %H:%M')}\n"
                            f"({int(age/60)}分前)\n"
                            f"PC・Task Schedulerの稼働を確認してください。"
                        )
                        await push_text_message(msg)
                        _alerted_today[name] = today_key
                        logger.warning(f"heartbeat stale: {name} age={int(age)}s")
                finally:
                    db.close()
        except Exception as e:
            logger.exception(f"heartbeat_checker error: {e}")

        # 5分ごとにチェック（ヒット時刻帯にあわせて発火する確度が上がる）
        await asyncio.sleep(300)
