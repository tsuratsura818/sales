"""ローカル Claude Code で既存 PipelineRun の提案文を高品質再生成するスタンドアロンCLI.

使い方:
    cd "C:/Users/nishikawa/Desktop/Claude Work/AllProject/sales"
    python scripts/regenerate_proposals.py --run-id 6
    python scripts/regenerate_proposals.py --run-id 6 --ranks S,A,B
    python scripts/regenerate_proposals.py --run-id 6 --dry-run

【重要】
Render UIで実行した PipelineRun は Render の Supabase Postgres に保存されている。
このスクリプトをローカルから走らせて Render 上の Run を更新したい場合は、
`.env` に Render と同じ DATABASE_URL を設定してから実行すること。

例:
    # .env に追記
    DATABASE_URL=postgresql://USER:PASS@xxx.supabase.co:5432/postgres

設定が無い場合はローカルの sales.db (sqlite) を見るので、Render の Run は見えない。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main() -> int:
    parser = argparse.ArgumentParser(description="PipelineRun の提案文を Claude Code で再生成")
    parser.add_argument("--run-id", type=int, required=True, help="対象 PipelineRun ID")
    parser.add_argument(
        "--ranks", default="S,A",
        help="再生成対象のランク(カンマ区切り、例: S,A,B)"
    )
    parser.add_argument("--dry-run", action="store_true", help="件数だけ表示して終了")
    args = parser.parse_args()

    from app.database import init_db, SessionLocal
    init_db()

    from app.models.pipeline import PipelineRun, PipelineResult
    from app.services import local_claude
    from app.services.pipeline.runner import _enrich_with_proposals

    if not local_claude.is_available():
        print("[エラー] claude CLI が見つかりません。Claude Code をインストールしてからやり直してください。")
        return 2

    rank_list = [r.strip().upper() for r in args.ranks.split(",") if r.strip()]

    db = SessionLocal()
    try:
        run = db.query(PipelineRun).filter(PipelineRun.id == args.run_id).first()
        if not run:
            print(f"[エラー] PipelineRun #{args.run_id} が見つかりません")
            return 1

        targets = (
            db.query(PipelineResult)
            .filter(
                PipelineResult.run_id == args.run_id,
                PipelineResult.rank.in_(rank_list),
                PipelineResult.website.isnot(None),
            )
            .all()
        )
        print(f"PipelineRun #{args.run_id} ({run.status}, created={run.created_at})")
        print(f"  ランク {rank_list} の website 持ち: {len(targets)}件")

        if args.dry_run:
            print("[dry-run] 終了")
            return 0

        if not targets:
            return 0

        # 既存の提案文をクリアして強制再生成
        for r in targets:
            r.personalized_subject = None
            r.personalized_body = None
        db.commit()

        await _enrich_with_proposals(targets, db)

        ok = sum(1 for r in targets if r.personalized_subject and r.personalized_body)
        print(f"[完了] 提案文を再生成: {ok}/{len(targets)}件")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
