import json
import re
import logging
from typing import Optional

import anthropic
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

EVALUATE_SYSTEM_PROMPT = """あなたはフリーランスのWeb制作者・デザイナーのアシスタントAIです。
求人案件がユーザーのスキルセットに合致するかを評価してください。

ユーザーのスキルセット:
- Webサイト制作（HTML/CSS/JavaScript, WordPress, React, Next.js）
- LP制作・コーディング
- ECサイト構築（Shopify, 自社EC）
- Webデザイン・UI/UX
- SEO対策・Webマーケティング
- レスポンシブデザイン
- サーバー構築・運用

以下の基準で0〜100点のスコアをつけてください:

高スコア（70-100）:
- 上記スキルに直接合致する案件
- 予算が適正（固定報酬5万円以上、時給1,500円以上）
- クライアントの評価が高い
- 納期に余裕がある

中スコア（40-69）:
- 一部スキルが合致するが、追加学習が必要
- 予算がやや低い
- 競争が激しそうな案件

低スコア（0-39）:
- スキルセットとの乖離が大きい
- 予算が極端に低い（相場の半分以下）
- 要件が不明確で炎上リスクが高い
- システム開発・アプリ開発など専門外

出力はJSON形式で返してください:
{"score": 85, "reason": "WordPress制作案件で予算も適正。取り組みやすい", "category": "web_development", "risk_flags": ["短納期"], "recommended_budget": 150000}

- reason は50文字以内の日本語で簡潔に
- category は "web_development", "seo_marketing", "ec_site" のいずれか
- risk_flags は懸念事項の配列（なければ空配列）
- recommended_budget は提案すべき金額（円）。見積もれない場合はnull
"""

PROPOSAL_SYSTEM_PROMPT = """あなたはフリーランスのWeb制作者として、クラウドソーシング案件への提案文を作成します。

## 提案文の構成（この順番で書く）
1. 挨拶（1文）: 「はじめまして。」+案件への関心を示す一文
2. 案件理解（2-3文）: クライアントの要望・課題を自分の言葉で要約し「理解していますよ」と伝える
3. 提案内容（3-4文）: 要件に対する具体的なアプローチ・使用技術・工夫ポイント
4. 実績（1-2文）: 関連する経験やスキルを簡潔に（盛りすぎない）
5. 進め方（1-2文）: 大まかな作業フロー・確認方法・納期の目安
6. 締め（1文）: 前向きな一文で終える

## トーン・文体
- 敬語だが堅すぎない（です・ます調）
- テンプレ感のない自然な文章
- 具体的な数値や技術名を入れて説得力を出す
- クライアントの立場に立った表現（「ご要望の〜」「お力になれると考えています」）

## 禁止事項
- 「何でもできます」系の漠然としたアピール
- 「格安で」「値引きします」等の価格訴求
- 過剰な自己PR（経歴の羅列）
- 不自然な改行・箇条書きの多用

## 出力ルール
- 400〜600文字程度
- 提案文のみを返す（JSON・見出し・装飾不要）
- 改行は自然な段落区切りのみ
"""


async def evaluate_job(
    title: str,
    description: str,
    budget_min: Optional[int],
    budget_max: Optional[int],
    budget_type: Optional[str],
    client_name: Optional[str],
    client_rating: Optional[float],
    platform: str,
    user_profile: str = "",
) -> dict:
    """案件のマッチ度をClaudeで評価。score/reason/category/risk_flags/recommended_budgetを返す"""
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    budget_text = "不明"
    if budget_min and budget_max:
        if budget_min == budget_max:
            budget_text = f"{budget_min:,}円"
        else:
            budget_text = f"{budget_min:,}円 〜 {budget_max:,}円"
        if budget_type == "hourly":
            budget_text += "（時給）"

    client_info = ""
    if client_name:
        client_info = f"クライアント: {client_name}"
        if client_rating:
            client_info += f"（評価: {client_rating}）"

    from app.services.settings_service import get_monitor_settings
    ms = get_monitor_settings()

    system_prompt = ms.evaluate_system_prompt if ms.evaluate_system_prompt else EVALUATE_SYSTEM_PROMPT

    profile_text = user_profile or ms.user_profile_text or settings.USER_PROFILE_TEXT
    if profile_text:
        system_prompt += f"\n\nユーザーの追加プロフィール:\n{profile_text}"

    user_prompt = f"""以下の案件を評価してください。

プラットフォーム: {platform}
タイトル: {title}
説明: {description[:2000]}
予算: {budget_text}
{client_info}

JSON形式で評価を返してください。"""

    try:
        message = await client.messages.create(
            model=settings.CLAUDE_MODEL_EVAL,
            max_tokens=512,
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
        )

        content = message.content[0].text
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "score": int(data.get("score", 0)),
                "reason": data.get("reason", "評価不可"),
                "category": data.get("category", "web_development"),
                "risk_flags": data.get("risk_flags", []),
                "recommended_budget": data.get("recommended_budget"),
            }
    except Exception as e:
        logger.error(f"案件評価エラー: {e}")

    return {
        "score": 0,
        "reason": "評価エラー",
        "category": "web_development",
        "risk_flags": [],
        "recommended_budget": None,
    }


async def generate_proposal(
    title: str,
    description: str,
    budget_min: Optional[int],
    budget_max: Optional[int],
    platform: str,
    user_profile: str = "",
) -> str:
    """案件に合わせた提案文をClaudeで生成"""
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    from app.services.settings_service import get_monitor_settings
    ms = get_monitor_settings()
    profile_text = user_profile or ms.user_profile_text or settings.USER_PROFILE_TEXT or "Web制作・デザインの経験あり"

    budget_text = "記載なし"
    if budget_min and budget_max:
        if budget_min == budget_max:
            budget_text = f"{budget_min:,}円"
        else:
            budget_text = f"{budget_min:,}円〜{budget_max:,}円"

    # 説明文を1000文字に制限（トークンコスト削減）
    desc_truncated = description[:1000] if description else "詳細なし"

    user_prompt = f"""【案件情報】
タイトル: {title}
予算: {budget_text}
説明:
{desc_truncated}

【応募者プロフィール】
{profile_text}

この案件への提案文を作成してください。"""

    try:
        message = await client.messages.create(
            model=settings.CLAUDE_MODEL_PROPOSAL,
            max_tokens=1024,
            messages=[{"role": "user", "content": user_prompt}],
            system=PROPOSAL_SYSTEM_PROMPT,
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"提案文生成エラー: {e}")
        raise
