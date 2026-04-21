"""既存 Supabase contacts に対し本番用 Claude 提案文を一括生成 + キャンペーン化。

使い方:
    python scripts/generate_for_supabase_contacts.py
    python scripts/generate_for_supabase_contacts.py --limit 50  # まず少数でテスト
    python scripts/generate_for_supabase_contacts.py --campaign-name "本番第1弾"

フロー:
  1) Supabase contacts を取得(email + website 必須、generic email除外)
  2) Claude Code バッチで個別提案文を生成
  3) contact.custom_fields に proposal_subject_claude/proposal_body_claude を保存
  4) 新規 campaign 作成 (status=review)
  5) campaign_contacts INSERT (status=queued + Claude生成文面)
  6) Render UI URL を出力
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GENERIC_PREFIXES = ("info@", "contact@", "support@", "no_reply@", "noreply@", "sales@", "office@", "admin@")

EXCLUDED_DOMAINS = {
    "openwork.jp", "rikunabi.com", "doda.jp", "mynavi.jp", "indeed.com",
    "wantedly.com", "linkedin.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "wikipedia.org", "note.com", "ameblo.jp", "hatenablog.com",
    "prtimes.jp", "tabelog.com", "hotpepper.jp",
}


def is_production_worthy(c: dict) -> tuple[bool, str]:
    email = (c.get("email") or "").lower().strip()
    web = (c.get("website_url") or "").lower().strip()
    if not email or not web:
        return False, "missing_email_or_website"
    if any(email.startswith(p) for p in GENERIC_PREFIXES):
        return False, "generic_email"
    for d in EXCLUDED_DOMAINS:
        if d in web:
            return False, f"excluded_domain:{d}"
    return True, ""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0=全件")
    parser.add_argument("--campaign-name", default="本番第1弾(Claude生成)")
    parser.add_argument("--chunk-size", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # dotenv読み込み(他モジュールのos.getenvが効くように)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from app.services import local_claude, mailforge_client as mf
    from app.services import proposal_service

    if not local_claude.is_available():
        print("[ERROR] claude CLI が見つかりません")
        return 2

    print("[1/5] Supabase から contacts 取得中...")
    import httpx
    USER_ID = mf.USER_ID
    KEY = mf.SUPABASE_KEY
    BASE = mf.API_BASE
    H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}

    r = httpx.get(f"{BASE}/contacts", headers=H,
                  params={"user_id": f"eq.{USER_ID}",
                          "select": "id,email,company_name,industry,website_url,custom_fields,notes",
                          "limit": "2000"}, timeout=30)
    contacts = r.json()
    print(f"  取得: {len(contacts)}件")

    print("\n[2/5] 本番フィルタ適用中...")
    survivors = []
    skip_reasons: dict[str, int] = {}
    for c in contacts:
        ok, reason = is_production_worthy(c)
        if ok:
            survivors.append(c)
        else:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    print(f"  残った: {len(survivors)}件")
    for r, n in sorted(skip_reasons.items(), key=lambda x: -x[1]):
        print(f"  除外 {n}件: {r}")

    if args.limit > 0:
        survivors = survivors[:args.limit]
        print(f"\n  --limit {args.limit} を適用 → {len(survivors)}件")

    if args.dry_run:
        print("\n[dry-run] 終了")
        return 0

    if not survivors:
        print("対象なし、終了")
        return 0

    # Claude バッチ用 dict 構築 (既存 custom_fields をシード情報として使う)
    print(f"\n[3/5] Claude バッチで提案文生成中 (chunk={args.chunk_size}, 約{(len(survivors)//args.chunk_size+1)*15}秒)...")
    targets = []
    for c in survivors:
        cf = c.get("custom_fields") or {}
        # 既存テンプレ提案文をヒントとして渡す(Claudeが業界文脈を把握しやすい)
        seed_proposal = cf.get("proposal_body", "")[:300]
        targets.append({
            "url": c.get("website_url") or "",
            "company": c.get("company_name") or "",
            "industry": c.get("industry") or "",
            "category": cf.get("category") or "B",
            "prefecture": cf.get("prefecture") or "",
            "analysis": {"_seed_hint": seed_proposal},
        })

    proposals = await proposal_service.generate_batch_proposals(targets, chunk_size=args.chunk_size)
    ok_count = sum(1 for p in proposals if p.get("subject") and p.get("body"))
    print(f"  生成成功: {ok_count}/{len(proposals)}件")

    # contacts.custom_fields に Claude 版を保存
    print("\n[4/5] contacts.custom_fields を更新中...")
    updated = 0
    for c, prop in zip(survivors, proposals):
        if not prop.get("subject") or not prop.get("body"):
            continue
        new_cf = dict(c.get("custom_fields") or {})
        new_cf["proposal_subject_claude"] = prop["subject"]
        new_cf["proposal_body_claude"] = prop["body"]
        try:
            httpx.patch(f"{BASE}/contacts",
                        headers=H,
                        params={"id": f"eq.{c['id']}"},
                        json={"custom_fields": new_cf},
                        timeout=15)
            updated += 1
        except Exception as e:
            print(f"  [warn] update {c['email']}: {e}")
    print(f"  更新: {updated}件")

    # キャンペーン作成
    print(f"\n[5/5] キャンペーン作成: {args.campaign_name!r}")
    campaign = mf.create_campaign({
        "name": args.campaign_name,
        "status": "review",
        "sender_name": "西川",
        "send_start_time": "09:00",
        "send_end_time": "18:00",
        "send_days": [1, 2, 3, 4, 5],
        "min_interval_sec": 120,
        "max_interval_sec": 300,
        "total_contacts": 0,
        "subject_template": "(個別生成済み Claude)",
        "body_template": "(個別生成済み Claude)",
    })
    if not campaign or not campaign.get("id"):
        print(f"  [ERROR] campaign作成失敗: {campaign}")
        return 1
    cid = campaign["id"]
    print(f"  campaign_id: {cid}")

    items = []
    for c, prop in zip(survivors, proposals):
        if not prop.get("subject") or not prop.get("body"):
            continue
        items.append({
            "contact_id": c["id"],
            "personalized_subject": prop["subject"],
            "personalized_body": prop["body"],
        })
    cc_result = mf.create_campaign_contacts(cid, items)
    print(f"  campaign_contacts: {cc_result}")

    if cc_result.get("inserted", 0) > 0:
        mf.update_campaign(cid, {"total_contacts": cc_result["inserted"]})

    print(f"\n✅ 完了")
    print(f"   Render UI: https://sales-6g78.onrender.com/mail/campaigns/{cid}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
