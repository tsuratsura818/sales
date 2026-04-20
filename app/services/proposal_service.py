"""提案文生成サービス (ローカル Claude Code CLI 経由)

旧 `claude_service.py` (Anthropic API 直呼び出し) の置き換え。
ユーザーのローカル Claude Code 認証を利用して subprocess 経由で生成する。

公開API (後方互換):
  - generate_email(lead, portfolio_text="") → (subject, body)
  - generate_followup_email(lead, step_number, previous_subjects, portfolio_text="") → (subject, body)
  - generate_competitor_email(lead, comparison_data, portfolio_text="") → (subject, body)
  - generate_batch_proposals(targets) → list[dict]  (pipeline バッチ用・新規)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.models.lead import Lead
from app.services.local_claude import ClaudeCliError, extract_json, invoke

log = logging.getLogger("proposal_service")


# ============================================================
# システムプロンプト
# ============================================================

SYSTEM_PROMPT_EMAIL = """あなたはWeb制作・デザイン・ECサイト制作を手がける会社のベテラン営業担当者です。
相手企業のWebサイトに見つかった具体的な問題点を礼儀正しく、かつ価値提供を重視した形で指摘し、
最適な提案の営業メールを作成してください。

あなたの会社が提供できるサービス：
- Webサイト制作・リニューアル（HTML/CSS/JS、WordPress、モダンフレームワーク）
- デザイン改善（UI/UX、ブランディング、OGP/SNS最適化）
- ECサイト構築・改善（自社EC、Shopify、カスタムEC）
- SEO対策・構造化データ対応
- アクセシビリティ改善

検出された問題に応じて、最も刺さる提案を選んでください：
- セキュリティ問題 → まず安全性改善を提案
- デザインの古さ → リニューアル・ブランディング提案
- EC関連の問題 → EC改善・自社EC移行提案
- SEO問題 → 検索順位改善・集客向上提案
- 複数問題がある場合 → 最もインパクトの大きい2〜3点に絞る

以下のルールを守ってください：
- 押しつけがましくせず、相手の立場を尊重する
- 具体的な問題点を数字や事実を使って説明する
- 改善によるメリットを明確に伝える
- 自社の制作実績（ポートフォリオ）が提供された場合、同業種や関連する実績を1〜2件、本文中に自然に組み込む
  - 例: 「同じ○○業界の△△様では、リニューアル後にお問い合わせが3倍になりました」
  - 実績がない場合はこの部分は省略する
- 締めくくりはお問い合わせへの誘導
- 件名と本文をJSONで返す: {"subject": "件名", "body": "本文"}
- 日本語で作成する
- 本文は300〜500文字程度
- プリアンブル(「承知しました」等)やコードフェンスは一切付けず、JSONのみを出力すること
"""

FOLLOWUP_SYSTEM_PROMPTS: dict[int, str] = {
    2: """あなたはWeb制作・デザイン・ECサイト制作を手がける会社のベテラン営業担当者です。
3日前に初回の営業メールを送信しましたが、返信がありません。
今回は【別の切り口】からアプローチしてください。

切り口の例：
- 同業他社の成功事例を紹介する
- 具体的なコスト削減効果や数字を提示する
- 季節やトレンドに合わせた提案をする
- 問題を放置した場合のリスクを具体的に伝える

以下のルール：
- 前回メールの繰り返しにならないようにする
- 押しつけがましくない、自然なフォローアップ
- 件名に「Re:」をつけず、新しい切り口の件名にする
- 本文200〜400文字程度
- JSON形式で返す: {"subject": "件名", "body": "本文"}
- 日本語で作成する
- JSON以外の文字(コードフェンス・プリアンブル)は絶対に付けない
""",
    3: """あなたはWeb制作・デザイン・ECサイト制作を手がける会社のベテラン営業担当者です。
1週間前に初回メール、3日前にフォローアップメールを送信しましたが返信がありません。
これが最後のアプローチです。

最後のメールでは：
- 期間限定の無料診断や割引を提案する
- 具体的な改善事例（Before/After）を1つ挙げる
- 「お忙しいところ恐れ入りますが」と相手を気遣う
- これ以上のご連絡は控える旨を伝える（安心感）

以下のルール：
- 簡潔で誠実なトーン
- 本文200〜350文字程度
- JSON形式で返す: {"subject": "件名", "body": "本文"}
- 日本語で作成する
- JSON以外の文字(コードフェンス・プリアンブル)は絶対に付けない
""",
}

COMPETITOR_SYSTEM_PROMPT = """あなたはWeb制作・デザイン・ECサイト制作を手がける会社のベテラン営業担当者です。
対象企業のサイトを同業他社と比較分析した結果をもとに、説得力のある営業メールを作成してください。

ポイント：
- 「同業の競合サイトはこの機能を導入済み」という事実ベースの説得
- 競合に遅れを取っていることを脅かすのではなく、改善のチャンスとして提示
- 具体的な数字（競合の○%が対応済み等）を盛り込む
- 最もインパクトの大きいギャップ2〜3点に絞る
- 押しつけがましくせず、相手を気遣うトーン

あなたの会社が提供できるサービス：
- Webサイト制作・リニューアル
- デザイン改善（UI/UX、ブランディング）
- ECサイト構築・改善
- SEO対策・構造化データ対応

以下のルール：
- 件名と本文をJSON形式で返す: {"subject": "件名", "body": "本文"}
- 日本語で作成する
- 本文は300〜500文字程度
- JSON以外の文字(コードフェンス・プリアンブル)は絶対に付けない
"""

SYSTEM_PROMPT_BATCH = """あなたはWeb制作・デザイン・ECサイト制作を手がける会社のベテラン営業担当者です。
渡される企業リストの各社について、Webサイトの課題を踏まえたパーソナライズ営業メールを作成してください。

ルール：
- 押しつけがましくせず、相手の立場を尊重する
- 具体的な問題点を数字や事実を使って説明する
- 改善によるメリットを明確に伝える
- 締めくくりはお問い合わせへの誘導
- 本文300〜500文字程度
- 日本語で作成

出力形式（厳守）：
- 入力配列と同じ順序・同じ長さのJSON配列を返す
- 各要素は {"subject": "件名", "body": "本文"} 形式
- JSON以外の文字(プリアンブル・コードフェンス・解説)は一切付けない
"""


# ============================================================
# 問題点テキスト生成（score_breakdown → 人間可読テキスト）
# ============================================================

def _build_issues_text(lead: Lead, score_breakdown: dict) -> str:
    current_year = datetime.now().year
    issues: list[str] = []

    if "no_https" in score_breakdown:
        issues.append("・HTTPSに対応していない（Googleの検索ランキング低下・ブラウザの警告表示のリスク）")
    if "no_mobile" in score_breakdown:
        issues.append("・スマートフォン対応（レスポンシブデザイン）がされていない（モバイルユーザーの離脱率が高い傾向）")
    if "old_copyright_3yr" in score_breakdown and lead.copyright_year:
        years_ago = current_year - lead.copyright_year
        issues.append(f"・コピーライト表記が{lead.copyright_year}年（{years_ago}年前）のまま更新されていない")
    if "old_domain_10yr" in score_breakdown and lead.domain_age_years:
        issues.append(f"・サイト開設から約{int(lead.domain_age_years)}年が経過しており、デザインや技術的なアップデートが必要な可能性")
    if "has_flash" in score_breakdown:
        issues.append("・Flash技術を使用しているコンテンツがある（現在のブラウザでは表示不可）")
    if "ssl_expiry_90days" in score_breakdown:
        issues.append("・SSL証明書の有効期限が近づいている（セキュリティリスク）")
    if "old_wordpress" in score_breakdown and lead.cms_type and lead.cms_version:
        issues.append(f"・{lead.cms_type} {lead.cms_version}を使用しており、セキュリティパッチの適用が必要")
    if "low_pagespeed" in score_breakdown and lead.pagespeed_score is not None:
        issues.append(f"・ページ表示速度スコアが{lead.pagespeed_score}点（100点満点）と低く、ユーザー体験や検索順位に影響")
    if "no_og_image" in score_breakdown:
        issues.append("・OGP画像が未設定（SNSでシェアされた際にサムネイルが表示されず、クリック率が低下）")
    if "no_favicon" in score_breakdown:
        issues.append("・ファビコンが未設定（ブラウザのタブやブックマークでブランド認知されにくい）")
    if "table_layout" in score_breakdown:
        issues.append("・テーブルレイアウトを使用した古いHTML構造（レスポンシブ対応が困難・保守性が低い）")
    if "many_missing_alt" in score_breakdown and lead.missing_alt_count:
        issues.append(f"・{lead.missing_alt_count}個の画像にalt属性が欠落（アクセシビリティ・SEOに悪影響）")
    if lead.is_ec_site:
        if lead.ec_platform:
            issues.append(f"・ECプラットフォーム: {lead.ec_platform}を使用中")
        if "ec_no_product_schema" in score_breakdown:
            issues.append("・商品の構造化データが未設定（Google Shoppingなど検索結果でのリッチ表示が不可）")
        if "ec_no_site_search" in score_breakdown:
            issues.append("・サイト内検索機能がない（商品数が多い場合、ユーザーが目的の商品を見つけにくい）")
    if "no_structured_data" in score_breakdown:
        issues.append("・構造化データ（JSON-LD等）が未実装（検索結果でのリッチスニペット表示ができない）")
    if "no_sitemap" in score_breakdown:
        issues.append("・sitemap.xmlが未設置（検索エンジンのクロール効率が低下）")

    return "\n".join(issues) if issues else "・全体的なデザインの刷新が推奨される状況"


def _issues_from_analysis(analysis: dict | None, category: str | None) -> str:
    """pipeline 経由の site_analyzer 結果から課題テキストを組み立てる"""
    if not analysis:
        return "・全体的なデザインの刷新が推奨される状況"
    lines: list[str] = []
    if not analysis.get("is_https"):
        lines.append("・HTTPSに対応していない")
    copyright_year = analysis.get("copyright_year")
    if copyright_year and copyright_year < datetime.now().year - 2:
        lines.append(f"・コピーライト表記が{copyright_year}年のまま更新されていない")
    ps = analysis.get("pagespeed_score")
    if ps is not None and ps < 50:
        lines.append(f"・ページ表示速度スコアが{ps}点と低い")
    if not analysis.get("has_og"):
        lines.append("・OGP画像が未設定でSNSシェア時のクリック率が低い")
    if not analysis.get("has_favicon"):
        lines.append("・ファビコン未設定")
    cms = analysis.get("cms_type")
    if cms:
        lines.append(f"・CMS: {cms}を使用中")
    issues = analysis.get("issues") or []
    for iss in issues[:4]:
        lines.append(f"・{iss}")
    return "\n".join(lines) if lines else "・全体的なデザインの刷新が推奨される状況"


# ============================================================
# 単発生成 — 後方互換API
# ============================================================

async def generate_email(lead: Lead, portfolio_text: str = "") -> tuple[str, str]:
    """単一リードの営業メール生成 (旧 claude_service.generate_email 互換)"""
    score_breakdown: dict[str, Any] = {}
    if lead.score_breakdown:
        try:
            score_breakdown = json.loads(lead.score_breakdown)
        except Exception:
            pass

    issues_text = _build_issues_text(lead=lead, score_breakdown=score_breakdown)

    site_type = "一般サイト"
    if lead.is_ec_site:
        platform_info = f"（{lead.ec_platform}）" if lead.ec_platform else ""
        site_type = f"ECサイト{platform_info}"

    portfolio_section = f"\n\n{portfolio_text}" if portfolio_text else ""

    user_prompt = f"""以下の情報をもとに、最適な営業メールを作成してください。

対象サイトURL: {lead.url}
ドメイン: {lead.domain or "不明"}
サイトタイトル: {lead.title or "不明"}
サイト種別: {site_type}
CMS: {lead.cms_type or "不明"} {lead.cms_version or ""}

検出された問題点（優先度順）:
{issues_text}
{portfolio_section}
件名と本文をJSON形式で返してください。
例: {{"subject": "【ご提案】〇〇様のホームページリニューアルについて", "body": "..."}}"""

    try:
        raw = await invoke(user_prompt, system_prompt=SYSTEM_PROMPT_EMAIL)
        data = extract_json(raw)
        if isinstance(data, dict):
            return (
                data.get("subject") or "ホームページリニューアルのご提案",
                data.get("body") or raw,
            )
    except ClaudeCliError as e:
        log.warning("generate_email failed: %s", e)

    return "ホームページリニューアルのご提案", ""


async def generate_followup_email(
    lead: Lead,
    step_number: int,
    previous_subjects: list[str],
    portfolio_text: str = "",
) -> tuple[str, str]:
    """フォローアップメール生成 (旧 claude_service.generate_followup_email 互換)"""
    system_prompt = FOLLOWUP_SYSTEM_PROMPTS.get(step_number, FOLLOWUP_SYSTEM_PROMPTS[2])

    issues_text = ""
    if lead.score_breakdown:
        try:
            breakdown = json.loads(lead.score_breakdown)
            issues_text = _build_issues_text(lead=lead, score_breakdown=breakdown)
        except Exception:
            pass

    prev_list = "\n".join(f"- {s}" for s in previous_subjects) if previous_subjects else "- （なし）"
    fu_portfolio_section = f"\n{portfolio_text}" if portfolio_text else ""

    user_prompt = f"""対象サイト: {lead.url}
ドメイン: {lead.domain or "不明"}
サイトタイトル: {lead.title or "不明"}

検出された問題点:
{issues_text or "・全体的なデザインの刷新が推奨される状況"}

過去に送信した件名:
{prev_list}
{fu_portfolio_section}
この企業に対して、新しい切り口でフォローアップメールを作成してください。
JSON形式で返してください: {{"subject": "件名", "body": "本文"}}"""

    try:
        raw = await invoke(user_prompt, system_prompt=system_prompt)
        data = extract_json(raw)
        if isinstance(data, dict):
            return (
                data.get("subject") or "ご提案のフォローアップ",
                data.get("body") or raw,
            )
    except ClaudeCliError as e:
        log.warning("generate_followup_email failed: %s", e)

    return "ご提案のフォローアップ", ""


async def generate_competitor_email(
    lead: Lead,
    comparison_data: dict,
    portfolio_text: str = "",
) -> tuple[str, str]:
    """競合比較データを使った営業メール生成 (旧 claude_service.generate_competitor_email 互換)"""
    features = comparison_data.get("features", {})
    gaps = comparison_data.get("gaps", [])
    advantages = comparison_data.get("target_advantages", [])
    comp_count = comparison_data.get("competitor_count", 0)

    gap_text = ""
    for key, feat in features.items():
        if feat.get("gap"):
            label = feat.get("label", key)
            if key == "pagespeed":
                target_val = feat.get("target", "不明")
                avg_val = feat.get("competitors_avg", "不明")
                gap_text += f"・{label}: 御社 {target_val}点 → 競合平均 {avg_val}点\n"
            else:
                rate = feat.get("competitors_rate", 0)
                gap_text += f"・{label}: 競合の{rate}%が対応済み → 御社は未対応\n"

    advantage_text = ""
    if advantages:
        advantage_text = "御社が競合より優れている点:\n"
        for a in advantages:
            advantage_text += f"・{a}\n"

    comp_portfolio_section = f"\n{portfolio_text}" if portfolio_text else ""

    user_prompt = f"""対象サイト: {lead.url}
ドメイン: {lead.domain or "不明"}
サイトタイトル: {lead.title or "不明"}

【競合比較分析結果】（同業{comp_count}社と比較）
競合サイトと比べて不足している点:
{gap_text or "・特に大きなギャップなし"}

{advantage_text}
{comp_portfolio_section}
この競合比較データを踏まえて、改善提案の営業メールを作成してください。
JSON形式で返してください: {{"subject": "件名", "body": "本文"}}"""

    try:
        raw = await invoke(user_prompt, system_prompt=COMPETITOR_SYSTEM_PROMPT)
        data = extract_json(raw)
        if isinstance(data, dict):
            return (
                data.get("subject") or "競合分析に基づくご提案",
                data.get("body") or raw,
            )
    except ClaudeCliError as e:
        log.warning("generate_competitor_email failed: %s", e)

    return "競合分析に基づくご提案", ""


# ============================================================
# バッチ生成 — pipeline用 (新規)
# ============================================================

async def generate_batch_proposals(
    targets: list[dict],
    *,
    chunk_size: int = 12,
    timeout_per_chunk: int = 900,
) -> list[dict]:
    """複数リードの提案文を1回のCLI呼び出しでまとめて生成する。

    入力:
      targets = [{
        "url": str,
        "company": str,
        "industry": str,
        "category": str,  # A/B/C/D or None
        "prefecture": str,
        "analysis": dict | None,  # site_analyzer の出力 (dataclass asdict)
      }, ...]

    出力: 入力と同じ順序・同じ長さの list[{"subject": str, "body": str}]
          失敗した要素は {"subject": "", "body": ""}
    """
    if not targets:
        return []

    results: list[dict] = []
    total = len(targets)
    log.info(f"batch proposal generate: {total}件 (chunk={chunk_size})")

    for start in range(0, total, chunk_size):
        chunk = targets[start:start + chunk_size]
        user_prompt = _build_batch_prompt(chunk)

        try:
            raw = await invoke(
                user_prompt,
                system_prompt=SYSTEM_PROMPT_BATCH,
                timeout=timeout_per_chunk,
            )
            data = extract_json(raw)
            if not isinstance(data, list):
                log.warning(f"batch chunk {start}: response is not a list ({type(data).__name__})")
                results.extend([{"subject": "", "body": ""}] * len(chunk))
                continue
            # 長さが合わない場合は切り詰め or 埋める
            if len(data) < len(chunk):
                data = list(data) + [{"subject": "", "body": ""}] * (len(chunk) - len(data))
            elif len(data) > len(chunk):
                data = data[:len(chunk)]
            for item in data:
                if isinstance(item, dict):
                    results.append({
                        "subject": str(item.get("subject") or ""),
                        "body": str(item.get("body") or ""),
                    })
                else:
                    results.append({"subject": "", "body": ""})
            log.info(f"  [{min(start + chunk_size, total)}/{total}] batch chunk done")
        except ClaudeCliError as e:
            log.error(f"batch chunk {start}-{start+len(chunk)} failed: {e}")
            results.extend([{"subject": "", "body": ""}] * len(chunk))

    return results


def _build_batch_prompt(chunk: list[dict]) -> str:
    """バッチ入力を1本のユーザープロンプトに整形"""
    items: list[str] = []
    for idx, t in enumerate(chunk, 1):
        analysis = t.get("analysis") or {}
        issues = _issues_from_analysis(analysis, t.get("category"))
        items.append(
            f"[{idx}] {t.get('company') or '(会社名不明)'}"
            f"\n  URL: {t.get('url') or ''}"
            f"\n  業種: {t.get('industry') or '不明'}"
            f"\n  カテゴリ: {t.get('category') or '-'}"
            f"\n  都道府県: {t.get('prefecture') or '不明'}"
            f"\n  検出された問題点:\n{issues}"
        )
    body = "\n\n".join(items)
    return (
        f"以下の{len(chunk)}社について、それぞれ営業メールを作成してください。\n\n"
        f"{body}\n\n"
        f"同じ順序のJSON配列で返してください。要素数はちょうど{len(chunk)}個です。\n"
        f'例: [{{"subject":"...","body":"..."}}, ...]'
    )
