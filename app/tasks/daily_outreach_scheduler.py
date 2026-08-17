"""日次自動アウトリーチ: 毎日きまった時刻に新規の営業メールを送るところまで自動化する。

週次アウトリーチ(`weekly_outreach_scheduler`)が「リストを作ってLINE通知、送信は手動」
なのに対し、こちらは送信まで通す:

  1) リスト収集     … 無料スクレイパー(category コレクター)で新規企業を集める
  2) サイト分析      … HTML を読んで課題を検出（外部API不要）
  3) 提案文生成      … Mac 常駐のローカル Claude（定額サブスク）で1社ずつ個別生成
  4) キャンペーン投入 … MailForge に contacts + campaign_contacts(queued) を作成
  5) 送信開始        … campaign を status=sending にして MailForge の送信cronに任せる
  6) LINE 通知       … 実行結果を報告

【コストについて】
このタスクは従量課金の経路を一切使わない。
  - 収集: category コレクター = HTML スクレイピング（SerpAPI は使わない）
  - 生成: ローカル Claude（CLI もしくは Mac 常駐ブリッジ）= 定額サブスク枠
  - 送信: MailForge の SMTP = 自前アカウント
SerpAPI を使う google コレクターは従量課金なので収集元から常に除外している
（`_daily_sources()` 参照）。

【安全弁】
  - 既定は無効(`daily_outreach_enabled=False`)。/today のトグルで明示的にONにする
  - 1日の送信上限 `daily_outreach_daily_cap`（既定20件）
  - 配信停止リスト(suppression)に載っている宛先は除外
  - 送信済みは `PipelineResult.queued_at` で記録し、二重送信しない
  - 同日中の二重実行は `daily_outreach_last_date` でガード
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_

from app.config import get_settings
from app.database import SessionLocal
from app.models.app_settings import AppSettings
from app.models.pipeline import PipelineRun, PipelineResult
from app.services import line_service
from app.services import mailforge_client as mf
from app.services.company_profile import append_boilerplate
from app.services.pipeline.extractors import clean_company_name, looks_like_company
from app.services.suppression_service import is_suppressed

logger = logging.getLogger(__name__)
settings = get_settings()
JST = timezone(timedelta(hours=9))

BASE_URL = "https://sales-6g78.onrender.com"

# 収集は無料スクレイパーのみ。google(SerpAPI=従量課金)は使わない。
def _daily_sources() -> tuple[list[str], str]:
    """(使うコレクター, パイプラインのモード) を実行環境に応じて決める。

    どれも無料。google コレクターだけは SerpAPI（従量課金）なので常に外す。

    Mac常駐では category に加えて EC系コレクター(Yahoo!ショッピング/楽天/DuckDuckGo)
    も回す。EC出店状況が取れるぶんスコアが上がって rank S/A になりやすく、
    Web/EC制作の営業先としても狙いが合う。母数も増えるので50件/日に近づく。
    Render では10分で殺されるため category 1本に絞る。
    """
    if _is_render():
        return ["category"], "category"
    return ["yahoo", "rakuten", "duckduckgo", "category"], "both"
CATEGORY_ROTATION = ["A", "B", "C", "D"]

# 収集量は実行環境で変える。
#
# Render無料プランは10分程度でインスタンスを再起動し、実行中の asyncio タスクを
# 殺す（run#12 で uptime 610秒→28秒 の巻き戻りを実測）。パイプラインは最後まで
# 走り切らないと結果を保存しないため、途中で殺されると収集がまるごと無駄になる。
# 実測 約3分/カテゴリなので、Render では1カテゴリに絞らないと完走できない。
#
# Mac常駐（launchd）にはこの制限が無いので、全カテゴリを回して量を稼ぐ。
# 毎日20件送るにはこちらが前提になる。
def _is_render() -> bool:
    import os
    return bool(os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"))


def _collect_scope(day_index: int) -> tuple[list[str], int, int, int]:
    """(カテゴリ, 都道府県数, クエリ上限/カテゴリ, URL上限/カテゴリ) を環境で決める。

    毎日の必要数は「収集20・提案文20・送信20」。集めすぎても提案文を作らない
    ぶんは寝かせるだけで、収集にかかる時間も無駄になる。
    実測の目安: 1カテゴリ×10県/クエリ20/URL60 → 7件、
    4カテゴリ×16県/クエリ20/URL60 → 69件、4カテゴリ×24県/クエリ100/URL300 → 164件。
    1カテゴリ×24県/クエリ30/URL80 で 20〜30件になる見込み。
    """
    if _is_render():
        # 10分で殺されるため小さめ
        return [CATEGORY_ROTATION[day_index % len(CATEGORY_ROTATION)]], 10, 20, 60
    # Mac常駐でも、1日に必要なぶんだけ集める。カテゴリは日替わり。
    return [CATEGORY_ROTATION[day_index % len(CATEGORY_ROTATION)]], 24, 30, 80


# 在庫が上限に届かないとき、収集を何回まで繰り返すか（Mac常駐のみ）。
# 1回あたり20〜40分かかるので、回しすぎない範囲で。
MAX_COLLECT_ROUNDS = 3

# 送信対象の条件。EC出店状況が取れる Yahoo/楽天由来のリードは rank S/A になるが、
# category コレクター由来は EC状況が付かないため構造的に rank B 止まりになる。
# そこで _import_to_mailforge と同じく「rank S/A」または「カテゴリ分類済み」を条件にする。
SEND_RANKS = ("S", "A")
MIN_CATEGORY_CONFIDENCE = 0.4

# Render が再起動すると実行中の asyncio タスクは死ぬが status は running のまま残る。
# このモジュールはアプリ起動時に import されるので、ここで採った時刻 ≒ プロセス起動時刻。
# 「今のプロセスより前に始まった run」は、そのタスクを持っていたプロセスが
# もう居ないので確実に死んでいる、と判定できる（時間しきい値より正確）。
PROCESS_STARTED_AT = datetime.now()
# プロセス内で本当に固まった場合の保険（再起動を挟まないケース）
STALE_RUN_MINUTES = 90

# 送信ウィンドウ（MailForge 側の送信cronが参照する）
SEND_START_TIME = "09:00"
SEND_END_TIME = "18:00"
SEND_DAYS = [1, 2, 3, 4, 5]
MIN_INTERVAL_SEC = 120
MAX_INTERVAL_SEC = 300


def _get_cfg() -> AppSettings | None:
    db = SessionLocal()
    try:
        return db.query(AppSettings).first()
    finally:
        db.close()


def _mark_run(date_str: str) -> None:
    db = SessionLocal()
    try:
        cfg = db.query(AppSettings).first()
        if cfg:
            cfg.daily_outreach_last_date = date_str
            db.commit()
    finally:
        db.close()


def _stock_query(db):
    """まだ送っていない、提案文が揃った送信可能リードのクエリ"""
    return (
        db.query(PipelineResult)
        .filter(
            PipelineResult.queued_at.is_(None),
            PipelineResult.excluded_reason.is_(None),
            PipelineResult.email.isnot(None),
            PipelineResult.personalized_subject.isnot(None),
            PipelineResult.personalized_body.isnot(None),
            or_(
                PipelineResult.rank.in_(SEND_RANKS),
                and_(
                    PipelineResult.category.isnot(None),
                    PipelineResult.confidence >= MIN_CATEGORY_CONFIDENCE,
                ),
            ),
        )
        .order_by(PipelineResult.score.desc(), PipelineResult.id)
    )


async def _collect(day_index: int, cap: int = 20) -> int:
    """1日分のリード収集を回す。収集できた件数を返す。

    カテゴリ(A〜D)と都道府県を日ごとにローテーションさせて、毎日同じ母集団を
    掘り返さないようにする。category モードで実際に検索クエリを変えるのは
    この2つ（runner の keyword_limit/offset は yahoo/rakuten 等の
    キーワード系コレクター用で、category コレクターには効かない）。
    """
    from app.services.pipeline.runner import run_pipeline
    from app.services.pipeline.category_collector import PREFECTURES

    categories, prefs_per_day, max_queries, max_urls = _collect_scope(day_index)
    sources, mode = _daily_sources()
    # 全都道府県を prefs_per_day 件ずつスライドさせながら回す
    offset = (day_index * prefs_per_day) % len(PREFECTURES)
    prefs = [PREFECTURES[(offset + i) % len(PREFECTURES)] for i in range(prefs_per_day)]

    category_config = {
        "categories": categories,
        "prefectures": prefs,
        "max_queries_per_category": max_queries,
        "max_urls_per_category": max_urls,
        # 収集の段階では提案文を作らない。選別を通った相手だけ後から生成する。
        # 集めた全件（実測164件）を生成すると Claude の利用枠を一度に使い切るため。
        "generate_proposals": False,
        # EC系コレクター(yahoo/rakuten/duckduckgo)が使う登録キーワードのローテーション。
        # 全件回すと重いので、日ごとにずらして一部だけ使う。
        "keyword_limit": 12,
        "keyword_offset": day_index * 12,
    }

    db = SessionLocal()
    try:
        # 既に走っているパイプラインがあれば重ねない。
        # ただし Render の再起動で asyncio タスクが死ぬと running のまま残り、
        # そのままだと以後ずっと収集がスキップされてしまうので、
        # STALE_RUN_MINUTES を過ぎたものは失敗扱いにして先へ進む。
        stale_before = datetime.now() - timedelta(minutes=STALE_RUN_MINUTES)
        for running in db.query(PipelineRun).filter(PipelineRun.status == "running").all():
            started = running.created_at
            # 今のプロセスより前に始まったものは、実行していたプロセスが既に居ない
            died_with_old_process = started and started < PROCESS_STARTED_AT
            timed_out = started and started < stale_before
            if died_with_old_process or timed_out:
                why = "プロセス再起動で中断" if died_with_old_process else "実行が長すぎるため打ち切り"
                logger.warning(
                    f"停止したままのパイプラインを失敗扱いにします: run_id={running.id} "
                    f"(開始 {started} / {why})"
                )
                running.status = "failed"
                running.error_message = f"実行中に中断（{why}）"
                running.completed_at = datetime.now()
                db.commit()
            else:
                logger.warning(f"パイプライン実行中のため収集をスキップ: run_id={running.id}")
                return 0

        run = PipelineRun(
            sources=json.dumps(sources),
            keywords_count=0,
            skip_mx=1,
            status="pending",
            mode=mode,
            category_config=json.dumps(category_config, ensure_ascii=False),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    logger.info(
        f"日次アウトリーチ: 収集開始 run_id={run_id} "
        f"env={'render' if _is_render() else 'local'} cat={categories} prefs={prefs}"
    )
    await run_pipeline(run_id)

    db = SessionLocal()
    try:
        run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
        found = run.total_found if run else 0
        if run and run.status == "failed":
            logger.error(f"日次アウトリーチ: 収集失敗 {run.error_message}")
    finally:
        db.close()
    return found


def _screenable_query(db):
    """選別にかけられるリード（提案文はまだ無くてよい）。

    選別は会社名・URL・業種だけで判定でき、提案文を必要としない。
    先に選別してから通ったものだけ生成することで、捨てる分の生成を避ける。
    """
    return (
        db.query(PipelineResult)
        .filter(
            PipelineResult.queued_at.is_(None),
            PipelineResult.excluded_reason.is_(None),
            PipelineResult.email.isnot(None),
            PipelineResult.website.isnot(None),
            or_(
                PipelineResult.rank.in_(SEND_RANKS),
                and_(
                    PipelineResult.category.isnot(None),
                    PipelineResult.confidence >= MIN_CATEGORY_CONFIDENCE,
                ),
            ),
        )
        .order_by(PipelineResult.score.desc(), PipelineResult.id)
    )


def _pick_candidates(limit: int, require_proposal: bool = True) -> list[dict]:
    """選別にかける候補を集める。配信停止リストに載っている宛先はここで除外する。

    require_proposal=False にすると提案文が未生成のものも対象にする
    （選別を先に済ませて、通ったものだけ生成するため）。
    セッションを跨いで使うので ORM オブジェクトではなく dict にして返す。
    """
    db = SessionLocal()
    try:
        picked: list[dict] = []
        seen_emails: set[str] = set()
        q = _stock_query(db) if require_proposal else _screenable_query(db)
        for r in q.limit(limit * 3).all():
            if len(picked) >= limit:
                break
            email = (r.email or "").strip().lower()
            if not email or email in seen_emails:
                continue
            if is_suppressed(email, db):
                logger.info(f"配信停止リストのためスキップ: {email}")
                continue
            # 会社名として成立しないもの（記事見出し等）は宛名にできない。
            # 収集時のフィルタを通っていない在庫が残っているためここでも見る。
            company = clean_company_name(r.company or "")
            if not looks_like_company(company):
                logger.info(f"会社名として不適当なためスキップ: {(r.company or '')[:30]}")
                continue
            seen_emails.add(email)
            picked.append({
                "id": r.id,
                "email": r.email,
                "company": company,
                "industry": r.industry or "",
                "website": r.website or "",
                "platform": r.platform or "",
                "ec_status": r.ec_status or "",
                "category": r.category or "",
                "rank": r.rank or "",
                "score": r.score or 0,
                "source": r.source or "",
                "subject": r.personalized_subject,
                "body": r.personalized_body,
            })
        return picked
    finally:
        db.close()


SCREEN_SYSTEM_PROMPT = """あなたは営業リストの品質チェック担当です。
Web制作・EC構築の営業メールを送る相手として適切かどうかを1件ずつ判定してください。

【送ってよい】
- 事業者・店舗・士業・クリニック等が自分で運営している「自社サイト」

【送ってはいけない】
- メディア/ポータル/まとめ記事/観光ガイド/求人サイト/口コミサイトのページ
  （会社名の欄に記事タイトルが入っているものは、ほぼこれ）
- 大手プラットフォームや自治体・学校
- Web制作会社・広告代理店・デザイン事務所（同業）
- 会社の実体が読み取れないもの

迷ったら送らない（ok=false）側に倒してください。誤送信の方が損害が大きいためです。

入力と同じ順序・同じ要素数のJSON配列だけを返してください。
各要素: {"ok": true/false, "reason": "20文字程度の理由"}
プリアンブルやコードフェンスは付けないこと。"""


async def _screen_targets(targets: list[dict]) -> tuple[list[dict], list[dict]]:
    """送信直前にローカルClaudeで1件ずつ「営業して良い相手か」を判定する。

    収集コレクターは事業者の自社サイトと媒体記事ページを区別しきれず、
    会社名の欄に記事タイトルが入ったリードが混ざる。レビュー無しで送るため、
    ここで足切りする。ローカルClaude（定額枠）なので追加コストは発生しない。

    判定に失敗した場合は「送らない」側に倒す（fail-closed）。
    返り値: (通過したもの, 弾いたもの[reasonを付与])
    """
    from app.services import local_claude

    if not targets:
        return [], []

    items = []
    for i, t in enumerate(targets, 1):
        items.append(
            f"[{i}] 会社名として保存された値: {t['company'] or '(不明)'}"
            f"\n    URL: {t['website'] or '(なし)'}"
            f"\n    メール: {t['email']}"
            f"\n    業種: {t['industry'] or '不明'} / 分類: {t['category'] or '-'}"
        )
    prompt = (
        f"以下の{len(targets)}件を判定してください。\n\n"
        + "\n\n".join(items)
        + f"\n\n要素数ちょうど{len(targets)}個のJSON配列で返してください。"
    )

    try:
        from app.services.proposal_service import _proposal_model
        raw = await local_claude.invoke(
            prompt, system_prompt=SCREEN_SYSTEM_PROMPT,
            model=_proposal_model(), timeout=600,
        )
        verdicts = local_claude.extract_json(raw)
        if not isinstance(verdicts, list):
            raise ValueError(f"配列以外が返された: {type(verdicts).__name__}")
    except local_claude.ClaudeQuotaError as e:
        # 利用枠切れ。送らずに見送り、リセット時刻を通知に載せる。
        logger.error(f"日次アウトリーチ: 利用枠に達したため選別できず全件見送り: {e}")
        await _notify_text(
            "⏸ 日次アウトリーチを見送りました\n\n"
            "ローカルClaudeの利用枠に達したため、送信先の選別ができませんでした。\n"
            f"{str(e)[:200]}\n\n"
            "枠が戻れば次回の実行で自動的に再開します（収集済みのリードは残っています）。"
        )
        return [], []
    except Exception as e:
        logger.error(f"日次アウトリーチ: 選別に失敗したため全件見送り: {e}")
        await _notify_text(
            f"⚠️ 日次アウトリーチ: 選別でエラーが発生したため全件見送り\n{str(e)[:200]}"
        )
        return [], []

    passed: list[dict] = []
    rejected: list[dict] = []
    for t, v in zip(targets, verdicts):
        ok = isinstance(v, dict) and v.get("ok") is True
        reason = (v.get("reason") if isinstance(v, dict) else "") or "判定不能"
        if ok:
            passed.append(t)
        else:
            rejected.append({**t, "reason": reason[:200]})
    # 返り値が足りない分は見送り扱い
    for t in targets[len(verdicts):]:
        rejected.append({**t, "reason": "判定結果が返らなかった"})

    logger.info(f"日次アウトリーチ: 選別 {len(passed)}件通過 / {len(rejected)}件除外")
    for r in rejected:
        logger.info(f"  除外: {r['email']} ({r['company'][:30]}) — {r['reason']}")
    return passed, rejected


async def _generate_for(targets: list[dict]) -> dict[int, tuple[str, str]]:
    """指定したリードだけ提案文を生成し、{id: (件名, 本文)} を返す。

    選別を通った相手だけを対象にすることで、捨てるぶんの生成を避ける。
    """
    from app.models.pipeline import PipelineResult as PR
    from app.services.pipeline.runner import _enrich_with_proposals

    ids = [t["id"] for t in targets]
    db = SessionLocal()
    try:
        rows = db.query(PR).filter(PR.id.in_(ids)).all()
        logger.info(f"日次アウトリーチ: 選別通過した{len(rows)}件の提案文を生成します")
        await _enrich_with_proposals(rows, db)
        return {
            r.id: (r.personalized_subject, r.personalized_body)
            for r in rows
            if r.personalized_subject and r.personalized_body
        }
    except Exception as e:
        logger.exception(f"日次アウトリーチ: 提案文の生成でエラー: {e}")
        return {}
    finally:
        db.close()


def _mark_excluded(rejected: list[dict]) -> None:
    """選別で弾いたリードに理由を記録し、以後の対象から外す"""
    if not rejected:
        return
    db = SessionLocal()
    try:
        by_id = {r["id"]: r["reason"] for r in rejected}
        for r in db.query(PipelineResult).filter(PipelineResult.id.in_(by_id)).all():
            r.excluded_reason = by_id.get(r.id, "除外")
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"excluded_reason 記録エラー: {e}")
    finally:
        db.close()


def _push_to_mailforge(targets: list[dict], campaign_name: str) -> dict:
    """MailForge に contacts を upsert → キャンペーン作成 → 送信開始。

    campaign_contacts は status='queued' で投入するので MailForge 側の
    AI生成cron はスキップされ、こちらで作った提案文がそのまま配信される。
    同期I/Oなので呼び出し側で to_thread すること。
    """
    contacts_payload = [
        {
            "email": t["email"],
            "company_name": t["company"],
            "industry": t["industry"],
            "website_url": t["website"],
            "notes": " / ".join(x for x in (t["platform"], t["ec_status"]) if x),
            "custom_fields": {
                "category": t["category"],
                "rank": t["rank"],
                "score": str(t["score"]),
                "source": t["source"],
                "auto": "daily_outreach",
            },
        }
        for t in targets
    ]
    upsert_result = mf.upsert_contacts(contacts_payload)
    email_to_id = upsert_result.get("email_to_id", {})
    if not email_to_id:
        return {"error": f"contacts upsert 失敗: {upsert_result}", "sent": 0}

    campaign = mf.create_campaign({
        "name": campaign_name,
        "status": "sending",  # レビューを挟まずそのまま配信に乗せる
        "sender_name": "西川",
        "subject_template": "(個別生成済み)",
        "body_template": "(個別生成済み)",
        "send_start_time": SEND_START_TIME,
        "send_end_time": SEND_END_TIME,
        "send_days": SEND_DAYS,
        "min_interval_sec": MIN_INTERVAL_SEC,
        "max_interval_sec": MAX_INTERVAL_SEC,
        "total_contacts": 0,
    })
    if not campaign or not campaign.get("id"):
        return {"error": f"campaign 作成失敗: {campaign}", "sent": 0}
    campaign_id = campaign["id"]

    cc_items = []
    queued_ids = []
    for t in targets:
        cid = email_to_id.get(t["email"].lower())
        if not cid:
            continue
        # 会社紹介・実績・CTA・住所・配信停止は生成させず、ここで必ず連結する。
        # 生成結果が崩れても、法定表記と問い合わせ導線が欠けないようにするため。
        cc_items.append({
            "contact_id": cid,
            "personalized_subject": t["subject"],
            "personalized_body": append_boilerplate(t["body"]),
        })
        queued_ids.append(t["id"])

    cc_result = mf.create_campaign_contacts(campaign_id, cc_items)
    inserted = cc_result.get("inserted", 0)
    if inserted > 0:
        mf.update_campaign(campaign_id, {"total_contacts": inserted})
    else:
        # 1件も入らなかったキャンペーンは動かさない
        mf.update_campaign(campaign_id, {"status": "cancelled"})

    return {
        "campaign_id": campaign_id,
        "sent": inserted,
        "queued_ids": queued_ids if inserted > 0 else [],
        "error": cc_result.get("error"),
    }


def _promote_to_leads(result_ids: list[int], campaign_id: str | None = None) -> int:
    """送信したリードを Lead テーブルに昇格させる。

    選別と最終チェックを通ったリードは「営業して良いと確認済みの企業」であり、
    メール以外（電話・再アプローチ・商談管理）にも使える資産になる。
    pipeline_results に置いたままだと /leads の営業ワークフローから扱えないので、
    送信のタイミングで昇格させて蓄積する。
    """
    if not result_ids:
        return 0
    from app.models.pipeline import PipelineResult as PR
    from app.services.promotion_service import promote_to_lead

    db = SessionLocal()
    try:
        promoted = 0
        sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
        for r in db.query(PR).filter(PR.id.in_(result_ids)).all():
            try:
                lead = promote_to_lead(r, db)
                if lead:
                    promoted += 1
                else:
                    # 既に昇格済みでも送信実績は記録する
                    from app.models.lead import Lead
                    lead = db.query(Lead).filter(Lead.pipeline_result_id == r.id).first()
                if lead:
                    # status だけでは「生成済み」と「送信済み」が区別できないので
                    # 送信日時とキャンペーンIDを別に持たせる
                    lead.outreach_sent_at = sent_at
                    lead.outreach_campaign_id = campaign_id
                    lead.status = "email_sent"
                    db.commit()
            except Exception as e:
                db.rollback()
                logger.warning(f"リード昇格に失敗 (id={r.id}): {e}")
        if promoted:
            logger.info(f"日次アウトリーチ: {promoted}件をリード一覧に追加しました")
        return promoted
    except Exception as e:
        logger.exception(f"リード昇格でエラー: {e}")
        return 0
    finally:
        db.close()


def _mark_queued(result_ids: list[int], campaign_id: str) -> None:
    """送信キューに載せたリードに印をつけて二重送信を防ぐ"""
    if not result_ids:
        return
    db = SessionLocal()
    try:
        # DBの他の日時列は naive UTC（Postgres の func.now() / datetime.now() on Render）
        # なのでここも UTC で揃える。JSTで入れると一覧表示が9時間ずれる。
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for r in db.query(PipelineResult).filter(PipelineResult.id.in_(result_ids)).all():
            r.queued_at = now
            r.campaign_id = campaign_id
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"queued_at 記録エラー: {e}")
    finally:
        db.close()


async def _backfill_proposals(limit: int) -> int:
    """提案文が未生成のまま残っているリードを拾って生成する。

    Claude Max の利用枠を使い切ると生成だけが失敗し、収集済みのリードが
    提案文なしで取り残される（run#14 で69件が該当）。パイプラインは自分の
    実行分しか面倒を見ないので、翌日以降にここで拾い直す。
    """
    from app.models.pipeline import PipelineResult
    from app.services.pipeline.runner import _enrich_with_proposals

    db = SessionLocal()
    try:
        targets = (
            db.query(PipelineResult)
            .filter(
                PipelineResult.personalized_subject.is_(None),
                PipelineResult.queued_at.is_(None),
                PipelineResult.excluded_reason.is_(None),
                PipelineResult.website.isnot(None),
                PipelineResult.email.isnot(None),
                or_(
                    PipelineResult.rank.in_(SEND_RANKS),
                    and_(
                        PipelineResult.category.isnot(None),
                        PipelineResult.confidence >= MIN_CATEGORY_CONFIDENCE,
                    ),
                ),
            )
            .order_by(PipelineResult.score.desc(), PipelineResult.id)
            .limit(limit)
            .all()
        )
        if not targets:
            return 0
        logger.info(f"日次アウトリーチ: 提案文が未生成のリード{len(targets)}件を先に生成します")
        await _enrich_with_proposals(targets, db)
        return sum(1 for t in targets if t.personalized_subject and t.personalized_body)
    except Exception as e:
        logger.exception(f"提案文の追い生成でエラー: {e}")
        return 0
    finally:
        db.close()


async def run_daily_outreach(collect: bool = True, send: bool = True) -> dict:
    """日次アウトリーチを1回実行。収集→提案文→キャンペーン→送信開始まで。

    collect=False にすると収集を行わず、既にある在庫から選別・送信だけ行う
    （収集は済んでいるが生成や送信で失敗した場合のやり直し用）。

    send=False にするとMailForgeへの投入と送信済みマークを行わない。
    収集・生成・選別まで動かして中身を確認したいときに使う（ドライラン）。
    リードは在庫として残るので、確認後にそのまま送信できる。
    """
    from app.services import local_claude

    cfg = _get_cfg()
    cap = (getattr(cfg, "daily_outreach_daily_cap", 20) or 20) if cfg else 20
    if cap <= 0:
        return {"started": False, "reason": "送信上限が0", "sent": 0}

    now = datetime.now(JST)
    day_index = now.timetuple().tm_yday

    # 提案文はローカルClaude(定額)でしか作らない。使えないなら課金経路に
    # 落ちるのではなく、何もせず通知して終わる。
    # is_available() は subprocess + HTTP を叩くのでイベントループを塞がない
    if not await asyncio.to_thread(local_claude.is_available):
        await _notify_text(
            "⚠️ 日次アウトリーチを中止しました\n\n"
            "ローカルClaude（Mac常駐ブリッジ）に接続できません。\n"
            "提案文が作れないため収集・送信とも行いませんでした。\n\n"
            f"状態確認: {BASE_URL}/status"
        )
        logger.error("日次アウトリーチ: ローカルClaude利用不可のため中止")
        return {"started": False, "reason": "local_claude 利用不可", "sent": 0}

    # 在庫（提案文まで揃った未送信リード）が足りなければ収集する
    db = SessionLocal()
    try:
        # 提案文は選別後に作るので、在庫は「選別にかけられる件数」で数える
        stock = _screenable_query(db).count()
    finally:
        db.close()

    collected = 0
    if not collect:
        logger.info(f"日次アウトリーチ: 収集をスキップ（在庫{stock}件から選別・送信）")
    elif stock >= cap:
        logger.info(f"日次アウトリーチ: 在庫{stock}件で足りるため収集はスキップ")
    else:
        # 在庫が上限に届くまで収集を繰り返す。
        # 選別の通過率が低いので1回では届かないことが多い。都道府県は
        # ラウンドごとにずらして同じ母集団を掘り返さないようにする。
        # Render は10分で殺されるため1回だけにする。
        rounds = 1 if _is_render() else MAX_COLLECT_ROUNDS
        for rnd in range(rounds):
            logger.info(
                f"日次アウトリーチ: 在庫{stock}件 < 上限{cap}件 → "
                f"収集 {rnd + 1}/{rounds} 回目"
            )
            try:
                collected += await _collect(day_index + rnd * 7, cap)
            except Exception as e:
                logger.exception(f"日次アウトリーチ: 収集エラー(round {rnd + 1}): {e}")
                break

            db = SessionLocal()
            try:
                stock = _screenable_query(db).count()
            finally:
                db.close()
            if stock >= cap:
                logger.info(f"日次アウトリーチ: 在庫{stock}件に到達したので収集終了")
                break

    # 選別で落ちる分だけ余裕を持たせる（生成は選別後なので、ここが増えても
    # 生成件数は増えない。選別1回の入力が長くなるだけ）。
    candidates = _pick_candidates(cap * 2, require_proposal=False)
    if not candidates:
        await _notify_text(
            "📭 日次アウトリーチ: 送信できる新規リードがありませんでした\n\n"
            f"・今回の収集: {collected}件\n"
            "・提案文まで揃った未送信リード: 0件\n\n"
            f"{BASE_URL}/pipeline で状況を確認してください。"
        )
        return {"started": True, "collected": collected, "sent": 0}

    # レビュー無しで送るので、ここで「営業して良い相手か」を1件ずつ判定する。
    # 生成より先に選別することで、捨てる相手の提案文を作らずに済む。
    passed, rejected = await _screen_targets(candidates)
    _mark_excluded(rejected)
    targets = passed[:cap]

    # 選別を通ったものだけ提案文を作る（未生成のものがあれば生成する）
    need_generation = [t for t in targets if not t.get("subject")]
    if need_generation:
        generated = await _generate_for(need_generation)
        targets = [t for t in targets if t.get("subject") or t["id"] in generated]
        for t in targets:
            if t["id"] in generated:
                t["subject"], t["body"] = generated[t["id"]]
    if not targets:
        if candidates and not rejected:
            # _screen_targets がエラー/利用枠切れで通知済みのため二重送信しない
            return {"started": True, "collected": collected, "sent": 0, "screened_out": 0}
        await _notify_text(
            "📭 日次アウトリーチ: 選別を通過したリードがありませんでした\n\n"
            f"・今回の収集: {collected}件\n"
            f"・候補: {len(candidates)}件 → 選別で全件除外\n\n"
            f"{BASE_URL}/pipeline で状況を確認してください。"
        )
        return {
            "started": True, "collected": collected, "sent": 0,
            "screened_out": len(rejected),
        }

    if not send:
        # ドライラン: MailForgeへは投入せず、選別を通った内容を返すだけ。
        # queued_at も付けないので、確認後にそのまま本番送信できる。
        logger.info(
            f"日次アウトリーチ[ドライラン]: 送信せず終了。"
            f"収集{collected}件 / 候補{len(candidates)}件 / 除外{len(rejected)}件 / "
            f"送信対象{len(targets)}件"
        )
        return {
            "started": True, "dry_run": True, "collected": collected,
            "candidates": len(candidates), "screened_out": len(rejected),
            "would_send": len(targets),
            "targets": [
                {"company": t["company"], "email": t["email"], "website": t["website"],
                 "subject": t["subject"], "body": t["body"]}
                for t in targets
            ],
            "rejected": [
                {"company": r["company"], "email": r["email"], "reason": r["reason"]}
                for r in rejected
            ],
            "sent": 0,
        }

    campaign_name = f"日次アウトリーチ {now.strftime('%Y-%m-%d')}"
    try:
        result = await asyncio.to_thread(_push_to_mailforge, targets, campaign_name)
    except Exception as e:
        logger.exception(f"日次アウトリーチ: MailForge投入エラー: {e}")
        await _notify_text(f"⚠️ 日次アウトリーチ: MailForge投入に失敗しました\n{str(e)[:300]}")
        return {"started": True, "collected": collected, "sent": 0, "error": str(e)}

    sent = result.get("sent", 0)
    if result.get("error"):
        logger.error(f"日次アウトリーチ: {result['error']}")
    promoted = 0
    if sent > 0:
        queued_ids = result.get("queued_ids", [])
        _mark_queued(queued_ids, result["campaign_id"])
        # 選別と最終チェックを通った企業は資産として蓄積する
        promoted = _promote_to_leads(queued_ids, result.get("campaign_id"))

    await _notify(collected, sent, cap, len(rejected), result.get("campaign_id"), result.get("error"))
    return {
        "started": True,
        "collected": collected,
        "sent": sent,
        "screened_out": len(rejected),
        "promoted_leads": promoted,
        "campaign_id": result.get("campaign_id"),
    }


async def _notify_text(text: str) -> None:
    if not (settings.LINE_CHANNEL_ACCESS_TOKEN and settings.LINE_USER_ID):
        return
    try:
        await line_service.push_text_message(text[:4900])
    except Exception as e:
        logger.error(f"日次アウトリーチ通知エラー: {e}")


async def _notify(
    collected: int, sent: int, cap: int, screened_out: int,
    campaign_id: str | None, error: str | None,
) -> None:
    lines = [
        "📨 本日の営業メールを送信キューに投入しました",
        "",
        f"・新規収集: {collected}件",
        f"・選別で除外: {screened_out}件",
        f"・送信: {sent}件（上限 {cap}件/日）",
    ]
    if error:
        lines.append(f"・警告: {error[:200]}")
    if campaign_id:
        lines += ["", f"{BASE_URL}/mail/campaigns/{campaign_id}"]
    await _notify_text("\n".join(lines))
    logger.info(f"日次アウトリーチ完了: 収集{collected}件 / 送信{sent}件")


async def daily_outreach_scheduler() -> None:
    """10分ごとにチェックし、指定時刻を過ぎていてその日が未実行なら実行する。

    ただし Render 上では実行しない。無料プランは10分程度でインスタンスを
    再起動して実行中タスクを殺すため、収集を完走できないまま
    `daily_outreach_last_date` だけ進めてその日を潰してしまう。
    実行主体は Mac 常駐（launchd → scripts/run_daily_outreach.py）に一本化する。
    """
    await asyncio.sleep(60)

    if _is_render():
        logger.info(
            "日次アウトリーチ: Render では実行しません"
            "（10分で再起動され完走できないため、Mac常駐 launchd が実行します）"
        )
        return

    logger.info("日次アウトリーチスケジューラ開始（DB設定で有効/無効を制御）")

    while True:
        try:
            cfg = _get_cfg()
            if cfg and getattr(cfg, "daily_outreach_enabled", False):
                now = datetime.now(JST)
                today = now.strftime("%Y-%m-%d")
                target_hh = getattr(cfg, "daily_outreach_hour_jst", 10)
                weekdays_only = getattr(cfg, "daily_outreach_weekdays_only", True)
                last_date = getattr(cfg, "daily_outreach_last_date", None)

                is_weekend = now.weekday() >= 5
                if weekdays_only and is_weekend:
                    pass  # 土日は送らない
                elif last_date != today and now.hour >= target_hh:
                    # 先に「実行済み」を立ててから走らせる（長い処理中の二重起動防止）
                    _mark_run(today)
                    try:
                        await run_daily_outreach()
                    except Exception as e:
                        logger.exception(f"日次アウトリーチ実行エラー: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"日次アウトリーチスケジューラエラー: {e}")
        await asyncio.sleep(600)
