"""PipelineResult → Lead 昇格サービス

バッチ収集(`/pipeline`)で得た高ランクリードを、単発検索系の
営業ワークフロー(`/leads` 配下)で扱えるよう Lead テーブルに昇格させる。

- 重複チェック(同じ pipeline_result_id を持つ Lead が既にある場合はスキップ)
- 個別化提案文を generated_email_subject/body にコピー
- status='analyzed' or 'email_generated' で投入(分析済み扱い)
"""
from __future__ import annotations

import json
import logging
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.lead import Lead
from app.models.pipeline import PipelineResult

log = logging.getLogger("promotion_service")


def promote_to_lead(result: PipelineResult, db: Session) -> Lead | None:
    """1件の PipelineResult を Lead に昇格させる(既に昇格済みなら None)"""
    existing = (
        db.query(Lead)
        .filter(Lead.pipeline_result_id == result.id)
        .first()
    )
    if existing:
        return None

    # 提案文があれば status を email_generated に、無ければ analyzed
    has_proposal = bool(result.personalized_subject and result.personalized_body)
    status = "email_generated" if has_proposal else "analyzed"

    # site_analysis (JSON) からスコア breakdown へ最低限のキーをマップ
    score_breakdown = {}
    if result.site_analysis:
        try:
            sa = json.loads(result.site_analysis)
            if sa.get("is_https") is False:
                score_breakdown["no_https"] = True
            ps = sa.get("pagespeed_score")
            if ps is not None and ps < 50:
                score_breakdown["low_pagespeed"] = True
            if not sa.get("has_og"):
                score_breakdown["no_og_image"] = True
            if not sa.get("has_favicon"):
                score_breakdown["no_favicon"] = True
            cy = sa.get("copyright_year")
            if cy and isinstance(cy, int) and cy < 2023:
                score_breakdown["old_copyright_3yr"] = True
        except Exception:
            pass

    # 収集時に site_analyzer で診断済みなので、その結果を Lead の各列へ写す。
    # 写さないとリード一覧の HTTPS / モバイル / CMS / 著作権年が全て「-」になり、
    # 単発検索由来のリードと並べたときに未診断に見えてしまう。
    sa = {}
    if result.site_analysis:
        try:
            sa = json.loads(result.site_analysis)
        except Exception:
            sa = {}

    from urllib.parse import urlparse
    domain = urlparse(result.website or "").netloc or None

    lead = Lead(
        search_job_id=None,
        pipeline_result_id=result.id,
        url=result.website or "",
        domain=domain,
        title=result.company or "",
        status=status,
        contact_email=result.email or None,
        score=result.score or 0,
        score_breakdown=json.dumps(score_breakdown, ensure_ascii=False) if score_breakdown else None,
        conversion_rank=result.rank,
        industry_category=result.industry,
        generated_email_subject=result.personalized_subject,
        generated_email_body=result.personalized_body,
        # ここから診断結果
        is_https=sa.get("is_https"),
        has_viewport=sa.get("has_viewport"),
        # 「不明」は判定できなかったという意味なので、列には入れず空にする
        # （そのまま入れると一覧に「不明」というCMS名が表示されてしまう）
        cms_type=(sa.get("cms_type") or None) if sa.get("cms_type") not in ("", "不明", "None") else None,
        copyright_year=sa.get("copyright_year"),
        has_og_image=sa.get("has_og_image"),
        has_favicon=sa.get("has_favicon"),
        is_ec_site=sa.get("is_ec_site"),
        ec_platform=sa.get("ec_platform") or None,
        has_contact_form=sa.get("has_contact_form"),
        contact_page_url=sa.get("contact_url") or None,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    log.info(f"昇格: PipelineResult({result.id}) → Lead({lead.id})  email={result.email}")
    return lead


def promote_run(run_id: int, db: Session, *, ranks: Iterable[str] = ("S", "A")) -> dict:
    """指定 PipelineRun の中で対象ランクのリードを一括昇格する"""
    targets = (
        db.query(PipelineResult)
        .filter(
            PipelineResult.run_id == run_id,
            PipelineResult.rank.in_(list(ranks)),
        )
        .all()
    )
    promoted = 0
    skipped = 0
    for r in targets:
        lead = promote_to_lead(r, db)
        if lead:
            promoted += 1
        else:
            skipped += 1
    return {"promoted": promoted, "skipped_existing": skipped, "total_candidates": len(targets)}
