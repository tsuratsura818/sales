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

ユーザーのスキルセット（広めに対応可能）:
【Web制作】
- Webサイト制作・コーポレートサイト・採用サイト・ポートフォリオ（HTML/CSS/JavaScript, WordPress, React, Next.js）
- LP制作・ランディングページ
- ECサイト構築・運用（Shopify / BASE / STORES / 自社EC）
- レスポンシブデザイン・モバイル最適化

【デザイン】
- Webデザイン・UI/UX
- グラフィックデザイン・DTP（チラシ・パンフレット・名刺・ポスター・カタログ）
- ロゴ制作・ブランディング
- バナー・SNS用画像・サムネイル
- イラスト・キャラクターデザイン（簡単なものまで対応可）

【マーケ・運用】
- SEO対策・コンテンツSEO・内部対策
- Webマーケティング・CV改善
- Google広告・Meta広告の入稿/運用補助
- アクセス解析・GA4設定
- サイト保守・運用代行・更新作業

【ディレクション・運用】
- 要件整理・ヒアリング・ワイヤー設計
- 制作ディレクション・進行管理
- 既存サイト改修・部分修正
- サーバー設定・SSL・ドメイン移管

以下の基準で0〜100点のスコアをつけてください:

高スコア（70-100）:
- 上記スキルカテゴリのいずれかに合致する案件
- 予算が適正（固定報酬3万円以上、時給1,500円以上）
- クライアントの評価が高い、納期に余裕がある

中スコア（50-69）:
- 上記スキルに合致するが予算がやや低い、もしくは情報不足
- 短納期だが対応可能なボリューム
- ディレクションや進行が複雑そうな案件

中低スコア（30-49）:
- 一部スキルが合致するが学習コストや調査時間がかかる
- 競争激化や応募多数が予想される

低スコア（0-29）:
- 完全に専門外（スマホアプリ開発・組込みC/C++・大規模システム開発・機械学習・3D制作等）
- 予算が相場の1/3以下で炎上リスクが高い
- 要件が不明確で工数見積不能

【重要】以下は「合致」と判定する:
- DTP・チラシ・ロゴ・名刺・パンフレット → graphic_design / dtp_design として合致
- SEO相談・記事作成・コンテンツ制作 → seo_marketing として合致
- WordPress部分修正・既存サイト更新 → web_development として合致
- ECサイト運用・商品登録・Shopify改修 → ec_site として合致
- 保守運用・月額更新・小規模改修 → maintenance として合致
- ディレクション・進行管理・要件整理 → direction として合致
- バナー・SNS画像・サムネイル → graphic_design として合致

【強い減点条件 — 即0-15点】
- 「コピペで簡単」「未経験OK」「スマホ作業のみ」「初心者歓迎」「主婦歓迎」「副業向け」を含む
- 予算が「1000円以下」「時給800円未満」
- タイトル/本文に「副業」「アンケート」「データ入力」「タスク報酬」「タイピング」のみで具体技術が0
- 「動画編集量産」「YouTubeサムネ量産」「ライブ配信」「ゲーム配信」
- 「アフィリエイト誘導」「MLM」「ネットワークビジネス」
- 完全に専門外（スマホアプリ開発・組込みC/C++・大規模システム・機械学習・3D制作等）

【加点条件 — +10〜20】
- 「保守」「運用」「月額」「リテイナー」「継続」を含む（リピート性高い）
- 「Shopify」「WordPress」「Next.js」「Figma」を本文に含む
- 「大阪」「関西」「対面可」を含む（地理的アドバンテージ）
- 予算固定で10万円以上、または時給3000円以上
- クライアント評価4.5以上 + レビュー10件以上

【業種マッチボーナス — +5〜10】
- ユーザーの主要業種実績（飲食・不動産・美容・医療・製造業・士業）と一致する場合

出力はJSON形式で返してください:
{"score": 85, "reason": "WordPress制作案件で予算も適正。取り組みやすい", "category": "web_development", "risk_flags": ["短納期"], "recommended_budget": 150000}

- reason は50文字以内の日本語で簡潔に
- category は "web_development" / "seo_marketing" / "ec_site" / "graphic_design" / "dtp_design" / "maintenance" / "direction" / "out_of_scope" のいずれか
- risk_flags は懸念事項の配列（なければ空配列）
- recommended_budget は提案すべき金額（円）。見積もれない場合はnull
"""

PROPOSAL_SYSTEM_PROMPT = """あなたはフリーランスのWeb制作者として、クラウドソーシング案件への提案文を作成します。
返信率を高めることが目的です。テンプレ感を排除し、案件固有の言葉で書いてください。

## 提案文の構成（この順番で書く）
1. **挨拶**（1文）: 「はじめまして。」+ 案件タイトルに即した一言で関心を示す
2. **案件理解**（2-3文）: クライアントの要望・課題を自分の言葉で要約。曖昧な要件には触れて「ここはお伺いしたい」と書く
3. **提案内容**（3-4文）: 要件に対する具体的なアプローチ・使用技術・工夫ポイント。可能なら数値（〇営業日 / 〇円程度 / 〇P構成等）を入れる
4. **実績**（1-2文）: プロフィール内の関連実績から1〜2件を **業界・業種が近いものを優先**してピックアップして言及。URLが与えられていれば1つだけ自然に貼る（複数貼らない）
5. **質問・確認**（1-2文）: 案件詳細から不明な点を1〜2個、具体的に質問する（「ターゲット層は〇〇を想定されていますか」等）。これにより返信を引き出す
6. **進め方**（1文）: 「ヒアリング → ワイヤー → デザイン → コーディング → 公開」のような大まかな流れを1行で
7. **締め**（1文）: 前向きな一文で終える（「ぜひお力になれればと思っております」等）

## トーン・文体
- 敬語だが堅すぎない（です・ます調）
- テンプレ感のない自然な文章。案件タイトルや業種に即した語彙を使う
- 具体的な数値・技術名を入れて説得力を出す（WordPress / Shopify / Next.js / Figma 等）
- クライアントの立場に立った表現（「ご要望の〜」「お力になれると考えております」）

## 禁止事項
- 「何でもできます」系の漠然としたアピール
- 「格安で」「値引きします」等の価格訴求
- 過剰な自己PR（経歴の羅列）
- 不自然な改行・箇条書きの多用
- プロフィールに書かれていない実績や事例を捏造すること（必ずプロフィール記載の範囲内で）
- URL・電話番号・メールアドレスをプロフィール記載以外でつけ加えること

## 出力ルール
- 450〜650文字程度
- 提案文のみを返す（JSON・見出し・装飾不要）
- 改行は自然な段落区切りのみ
- 質問パートは「お伺いしたい点が1つございます。」のように軽く前置きしてから書く
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
