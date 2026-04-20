"""文字起こし → 議事録整形サービス (Claude)

minutes-cc-v2 の CLAUDE.md フォーマット規約をプロンプト化してClaudeに渡す。
"""

import json
from datetime import datetime

import anthropic

from app.config import get_settings


MINUTES_SYSTEM_PROMPT = """あなたは会議の議事録作成のプロフェッショナルです。
渡された文字起こしテキストから、指定されたフォーマットで議事録をMarkdownで生成してください。

# 事業名辞書 (表記揺れを正式名称に統一)

| 表記ゆれ例 | 正式名称 | 事業キー |
|-----------|---------|---------|
| つむぎ、Tsumugi、ツムギ | いとをかしTsumugi | tsumugi |
| コマパラ、4コマポータル | Komapara | komapara |
| 営業ツール、SalesTool、セルバディ | 営業Tool (SellBuddy) | sales |
| ウェブクラフト、WebCraft | WebCraft | webcraft |
| QRリダイレクト、ピボリンク | Pivolink | pivolink |
| プレスラボ、PressLab | PRESSLAB | presslab |
| 旅狼、ウルフギャング、たびろう | WOLFGANG | wolfgang |
| バナーフォージ | BannerForge Pro | bannerforge |
| 狼の森、おおかみのもり | オオカミの森 | okaminomori |
| アオン、おくり狼 | おくり狼のアオン | aon |
| クラフトビール、タップトゥブリュー | TAP TO BREW | taptobrew |
| フローリア大阪、なでしこ | フローリア大阪(女子サッカー) | florea |
| 医薬マーケ | 医薬マーケティングLab | general |

# 記述ルール
1. フィラー完全除去: 「えーと」「まあ」「そうですね」等は全カット
2. 不明瞭部分は無理に補完せず [不明瞭] を残す
3. 固有名詞は事業名辞書で正規化
4. 冗長禁止: 同じ内容を複数セクションに書かない
5. タイムスタンプ不要
6. 該当情報がないセクションは「特になし」と明記

# 必須セクション (この順序で出力)

```markdown
# 議事録: {YYYY-MM-DD} / {タイトル}

**日時**: {可能なら推定、不明なら空欄}
**関連プロジェクト**: {事業名辞書の正式名称、もしくは「該当なし」}
**参加者**: {推定含めて記載}

---

## サマリ
{3-5行。会議の核心のみ}

## 決定事項
- {動詞で始まる箇条書き。なければ「特になし」と明記}

## ToDo
- [ ] [担当] [内容] [期限]

## 論点・議論内容
### トピック1: {トピック名}
{内容}

### トピック2: {トピック名}
{内容}

## 次回アクション
{具体的な次の一手}

## 補足メモ
### Claude Code 引き継ぎ事項
- {Claude Codeで実装すべきタスクがあれば記載}

### アイデアメモ
- {保留・未決定のアイデアなど}
```

# 出力要件
- 必ず上記のMarkdownのみ返す (前後の挨拶・解説は禁止)
- JSON等で包まない、生のMarkdown文字列
- コードブロック(```)で全体を包まない
"""


async def transcript_to_minutes(
    transcript: str,
    project_hint: str | None = None,
    title_hint: str | None = None,
) -> str:
    """文字起こしをMarkdown議事録に整形する。

    Args:
        transcript: 文字起こし本文
        project_hint: プロジェクト名ヒント(あれば優先)
        title_hint: 会議タイトルヒント(あれば優先)

    Returns:
        Markdown形式の議事録文字列
    """
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY が設定されていません。")

    today = datetime.now().strftime("%Y-%m-%d")
    hint_lines = [f"- 今日の日付: {today}"]
    if project_hint:
        hint_lines.append(f"- 関連プロジェクト(指定): {project_hint}")
    if title_hint:
        hint_lines.append(f"- 会議タイトル(指定): {title_hint}")

    user_content = (
        "以下の文字起こしを議事録に整形してください。\n\n"
        "## ヒント\n" + "\n".join(hint_lines) + "\n\n"
        "## 文字起こし本文\n\n" + transcript
    )

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=settings.CLAUDE_MODEL_PROPOSAL,
        max_tokens=4096,
        system=MINUTES_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    text_blocks = [b.text for b in message.content if getattr(b, "type", None) == "text"]
    minutes_md = "\n".join(text_blocks).strip()

    # 念のためコードブロック剥がし
    if minutes_md.startswith("```"):
        lines = minutes_md.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        minutes_md = "\n".join(lines).strip()

    return minutes_md
