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
| SellBuddy | リード管理・分析・メール生成・案件モニター |
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

## 比較ビズ自動応募（ローカル実行）

`hikakubiz_watcher.py` がローカルPCで Gmail IMAP を監視し、`info@biz.ne.jp` からの新着案件メールを検知 → Playwright で比較ビズにログイン → 「開封して参加する」→ 「送信して参加する」を自動実行。テンプレは管理画面側のデフォルト（ヒアリング）をそのまま送信。

**前提**: `nishikawa@kitao-corp.jp` から `nishikawa@tsuratsura.com` への自動転送を `info@biz.ne.jp` 宛で設定済み。

**初回セットアップ**:
```bash
pip install playwright python-dotenv httpx
playwright install chromium
```

**実行**:
```bash
py hikakubiz_watcher.py            # 1回だけチェック（Task Scheduler想定）
py hikakubiz_watcher.py --watch    # 60秒間隔で常駐監視
```

**Windows Task Scheduler 設定済み**:
- タスク名: `HikakubizWatcher`
- スケジュール: 毎日 09:55 起動 / 1分間隔 / 35分間（= 09:55〜10:30 で計35回）
- 実行: `run_hikakubiz_watcher.bat`（python.exe を呼び、ログを `logs/hikakubiz_watcher.log` に追記）
- 多重起動防止: `.hikakubiz_watcher.lock` （PID + 5分TTL）
- 多重応募防止: `.hikakubiz_applied_tids.json` に応募済 tid を記録

**タスク管理 (PowerShell)**:
```powershell
# 状態確認
Get-ScheduledTask -TaskName HikakubizWatcher | Get-ScheduledTaskInfo
# 手動実行
Start-ScheduledTask -TaskName HikakubizWatcher
# 一時無効化
Disable-ScheduledTask -TaskName HikakubizWatcher
# 削除
Unregister-ScheduledTask -TaskName HikakubizWatcher -Confirm:$false
```

## 作業ルール

- 確認や質問は不要。自分で最適な判断をして進めてください
- ファイルの作成・編集は許可確認なしで実行してOK
- エラーが出たら自力で修正してください
- 完了したら「✅ 完了しました」と書いて、作業内容を簡潔に教えてください
