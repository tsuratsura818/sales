# CLAUDE.md — 営業Tool & コーポレートサイト AI

## プロジェクト概要

- **目的**: 弊社の営業ツール改修・コーポレートサイト改修をAIで管理・実行するプロジェクト
- **リポジトリ**: tsuratsura818/sales（`master`ブランチ → Render自動デプロイ）
- **スタック**: Python FastAPI + SQLAlchemy + Jinja2 + Playwright + Claude API
- **デプロイ**: Render (Docker) → `https://sales-6g78.onrender.com`
- **DB**: Supabase PostgreSQL

## 対象範囲

| 対象 | 概要 |
|------|------|
| 営業自動化ツール | リード管理・分析・メール生成・案件モニター |
| コーポレートサイト | 弊社コーポレートサイトの改修・更新 |

## 開発コマンド

```bash
pip install -r requirements.txt    # 依存インストール
uvicorn main:app --reload          # 開発サーバー
```

## Git 運用

- `master` ブランチに直接プッシュ → Render自動デプロイ

## 進行中タスク

- **スリープ対策**: UptimeRobot + GitHub Actions keep-alive + self-ping で対応中。改善しなければRender Starter($7/月)推奨

## 作業ルール

- 確認や質問は不要。自分で最適な判断をして進めてください
- ファイルの作成・編集は許可確認なしで実行してOK
- エラーが出たら自力で修正してください
- 完了したら「✅ 完了しました」と書いて、作業内容を簡潔に教えてください
