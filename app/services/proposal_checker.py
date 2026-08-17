"""生成された営業メールを Claude で最終チェックする。

文面の生成は ChatGPT（`ask.mjs` 経由・定額枠）に任せ、Claude は
「そのまま送ってよいか」の判定だけを担う。判定は入力も出力も短く、
1日1回の呼び出しで済むため Claude の利用枠をほとんど消費しない。

NG になったものは理由を添えて ChatGPT に書き直させ、
それでも直らなければ送信対象から外す（レビュー無しで送るため）。
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("proposal_checker")

CHECK_SYSTEM_PROMPT = """あなたは営業メールの最終チェック担当です。
レビュー無しでそのまま送信されるので、送ってはいけないものを確実に止めてください。

各メールについて、次の観点で判定します。

1. 宛名が実在する会社名か
   記事タイトル・地名の羅列・キャッチコピーが宛名になっていたらNG。
   例:「秋田観光スポット12選！外せない定番から…」「神戸 洋菓子 ギフト専門店」
   法人格が無くても、店名・屋号として自然ならOK。

2. 事実の創作が無いか
   「検出された問題点」に書かれていないことを断定していたらNG。
   例: 課題に店舗の記載が無いのに「店舗で知った方が」と書く。
   実績・事例・社名を創作していてもNG。

3. 数字の捏造が無いか
   「〇%改善」「売上〇倍」「手数料〇%」など、根拠の無い数字はNG。

4. 末尾が正しく止まっているか
   署名・会社名・連絡先・「お気軽にお問い合わせください」で終わっていたらNG
   （システム側の定型文と重複するため）。

5. 使い回しになっていないか
   他のメールとほぼ同じ言い回しで、その会社固有の話が無ければNG。

6. 失礼・不自然な日本語が無いか
   個人名に「ご担当者様」、宛名の会社名が入力と違う、など。

7. 内部記法が本文に漏れていないか
   営業メールに出てはいけない記号・ラベルが混ざっていたらNG。
   例:「〜が弱い → だから〜できない → その結果〜を取りこぼします」
       「(1) 事実：」「打ち手:」「仕組み:」のような見出し。
   矢印（→）で因果を並べる書き方は、そのままではメールとして不自然。

8. 「不明」を欠陥として断定していないか
   検出された問題点に「CMS: 不明」のように *不明* とある項目は、
   機械が判定できなかっただけで欠陥ではない。
   これを根拠に「更新しにくい」「確認しづらい」と書いていたらNG。

9. 引用マーク・出典表記が残っていないか
   生成時にウェブ検索の引用が混ざることがある。本文中に単独行で
   「Yahoo!ショッピング」「楽天市場」「+1」のようなサイト名や件数表示、
   [1] のような脚注番号が残っていたらNG。
   （文章の中で「Yahoo!ショッピングの貴社売場を拝見し」のように
     自然に使われている場合はOK。単独行や文脈から浮いているものだけNG）

入力と同じ順序・同じ要素数のJSON配列だけを返してください。
各要素: {"ok": true/false, "ng": ["該当した観点の番号"], "reason": "40字程度の理由"}

**問題が無いものは {"ok":true} だけを返してください**（ng と reason は省略可）。
説明を書くのは ok が false のものだけです。出力を短くするためです。

考えた過程は書かず、判定結果のJSONだけを返すこと。
JSON以外の文字（前置き・コードフェンス・解説）は一切付けないこと。"""


def build_check_prompt(items: list[dict]) -> str:
    """チェック対象をまとめた1本のプロンプトにする。

    判定に必要な最小限（会社名・検出課題・件名・本文）だけを渡す。
    URLや分析結果の全項目は判定に不要なので含めない（入力を小さく保つ）。
    """
    blocks = []
    for i, it in enumerate(items, 1):
        issues = it.get("issues") or "(記載なし)"
        blocks.append(
            f"[{i}] 会社名: {it.get('company') or '(不明)'}\n"
            f"検出された問題点: {issues}\n"
            f"件名: {it.get('subject') or ''}\n"
            f"本文:\n{it.get('body') or ''}"
        )
    return (
        f"以下の{len(items)}通を判定してください。\n\n"
        + "\n\n---\n\n".join(blocks)
        + f"\n\n要素数ちょうど{len(items)}個のJSON配列で返してください。"
    )


async def check_proposals(items: list[dict]) -> list[dict]:
    """まとめて判定し、[{ok, ng, reason}, ...] を返す。

    判定できなかった場合は「送らない」側に倒す（レビュー無しで送るため）。
    """
    from app.services import local_claude
    from app.services.proposal_service import _proposal_model

    if not items:
        return []

    try:
        # 20件で入力が約1万文字になる。分割すると呼び出し回数が増えて
        # 利用枠を余計に使うので、1回で投げてタイムアウト側を長く取る。
        raw = await local_claude.invoke(
            build_check_prompt(items),
            system_prompt=CHECK_SYSTEM_PROMPT,
            model=_proposal_model(),
            timeout=1800,
        )
        verdicts = local_claude.extract_json(raw)
        if not isinstance(verdicts, list):
            raise ValueError(f"配列以外が返った: {type(verdicts).__name__}")
    except Exception as e:
        logger.error(f"最終チェックに失敗したため全件見送り: {e}")
        return [{"ok": False, "ng": ["判定不能"], "reason": str(e)[:60]} for _ in items]

    out: list[dict] = []
    for i in range(len(items)):
        v = verdicts[i] if i < len(verdicts) else None
        if not isinstance(v, dict):
            out.append({"ok": False, "ng": ["判定不能"], "reason": "判定が返らなかった"})
            continue
        out.append({
            "ok": v.get("ok") is True,
            "ng": v.get("ng") or [],
            "reason": (v.get("reason") or "")[:120],
        })
    return out
