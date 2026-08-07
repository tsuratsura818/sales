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

## コスト方針（重要）

**定額枠以外のコストをかけない。** 従量課金のAPIを新しい自動化に組み込まないこと。

| 用途 | 使うもの（定額/無料） | 使わないもの（従量課金） |
|------|----------------------|------------------------|
| 文章生成 | ローカルClaude（CLI or Mac常駐ブリッジ）= サブスク枠 | Anthropic API (`ANTHROPIC_API_KEY`) |
| リスト収集 | category / yahoo / rakuten / duckduckgo コレクター（HTMLスクレイピング） | SerpAPI（`google_collector`。無料枠250/月） |
| メール送信 | MailForge の SMTP（自前アカウント） | - |

`app/services/local_claude.py` は Anthropic API を一切呼ばない。CLI が無い環境では
Mac常駐ブリッジにフォールバックし、それも不可なら `is_available()` が False を返すので、
呼び出し側は課金経路に落ちるのではなく処理を中止すること。

## ローカルClaudeブリッジ（Mac 24/7）

Mac に常駐している `claude_bridge.py` を cloudflared トンネルで公開し、
Render 側から HTTP でローカルClaude（サブスク枠）を呼べるようにしている。

- Mac側: launchd `com.tsuratsura.sellbuddy-bridge` → `~/sellbuddy-bridge.sh`
  → `claude_bridge.py` を :3949 で起動 + cloudflared トンネル
  → 公開URLを `POST /api/bridge/register` で Render に登録（`app_settings.local_bridge_url`）
- 呼び出し口:
  - `POST /claude` … 同期。ブラウザの秘書チャット等の短い依頼用
  - `POST /claude/async` → `GET /claude/job/<job_id>` … 非同期。**サーバー側からの長い生成はこちら**
    （Cloudflare は1リクエスト100秒で 524 を返すため、バッチ提案文生成は同期では通らない）
- サーバー側からの利用は `app/services/local_claude.invoke()` が自動で振り分ける
  （CLIがあれば subprocess、無ければブリッジの非同期ジョブ）

```bash
# 再起動（トンネルURLは自動で再登録される）
pkill -f claude_bridge.py
launchctl kickstart -k gui/501/com.tsuratsura.sellbuddy-bridge
```

## 日次自動アウトリーチ（毎日 新規営業メールを自動送信）

`app/tasks/daily_outreach_scheduler.py`。**レビューなしで実際に送信する**ので設定は既定OFF。

フロー: リスト収集 → サイト分析 → 提案文生成（ローカルClaude） → **送信前の選別** →
MailForge に contacts + campaign_contacts(`status=queued`) 投入 → campaign を
`status=sending` に → MailForge の送信cronが配信 → LINE通知。

### 送信前の選別（`_screen_targets`）

収集コレクターは事業者の自社サイトと媒体の記事ページを区別しきれない。実際に
run#9 では観光メディアの記事ページ2件が収集され、`company` に記事タイトルが
入った状態でカテゴリ分類も通過していた（つまりランク条件だけでは弾けない）。

レビュー無しで送るため、送信直前にローカルClaudeで1件ずつ
「営業して良い相手か」を判定する。定額枠なので追加コストはゼロ。

- 除外対象: メディア/ポータル/まとめ記事/求人/口コミ、自治体・学校、
  Web制作会社等の同業、実体が読み取れないもの
- **判定に失敗したら送らない**（fail-closed）
- 弾いたものは `pipeline_results.excluded_reason` に記録し、以後の対象から外す

### 送信対象の条件

`rank in (S, A)` **または** `category が付いていて confidence >= 0.4`。

rank だけで絞らないのは、`_score_lead` の rank A が60点を要求し、その配点の中心が
EC出店状況（Yahoo/楽天コレクター由来）のため。category コレクター由来のリードは
EC状況が付かず構造的に rank B 止まりになり、S/A だけだと対象が常に空になる。
`_import_to_mailforge` と同じ条件に揃えてある。

- 設定UI: `/today` の「📨 日次 自動送信」カード（ON/OFF・実行時刻・1日の送信上限・平日のみ）
- 手動実行: `POST /api/today/run-daily-outreach`
- 安全弁:
  - 既定OFF（`app_settings.daily_outreach_enabled`）
  - 1日の送信上限（既定20件）
  - 配信停止リスト（`suppression`）の宛先は除外
  - 送信済みは `pipeline_results.queued_at` / `campaign_id` に記録して二重送信しない
  - 同日の二重実行は `daily_outreach_last_date` でガード
  - **ローカルClaudeに繋がらない場合は収集も送信もせず中止**（課金経路に落ちない）
- 在庫（提案文まで揃った未送信リード）が上限に足りているときは収集をスキップして送信だけ行う

週次アウトリーチ（`weekly_outreach_scheduler`）はリスト作成＋LINE通知までで送信は手動。
用途が違うので併存させている。

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
python hikakubiz_watcher.py            # 1回だけチェック
python hikakubiz_watcher.py --watch    # 60秒間隔で常駐監視
```

**Mac launchd で常駐（現行）**:
- ラベル: `com.tsuratsura.sellbuddy-hikakubiz`
- 定義: `~/Library/LaunchAgents/com.tsuratsura.sellbuddy-hikakubiz.plist`
- 実行: `~/sales/.venv/bin/python hikakubiz_watcher.py --watch`（`RunAtLoad` + `KeepAlive`）
- ログ: `~/Library/Logs/sellbuddy-hikakubiz.{out,err}.log`
- 多重起動防止: `.hikakubiz_watcher.lock` （PID + 5分TTL）
- 多重応募防止: `.hikakubiz_applied_tids.json` に応募済 tid を記録

```bash
# 状態確認
launchctl list | grep sellbuddy-hikakubiz
# 再起動
launchctl kickstart -k gui/501/com.tsuratsura.sellbuddy-hikakubiz
# 一時停止 / 再開
launchctl bootout gui/501/com.tsuratsura.sellbuddy-hikakubiz
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.tsuratsura.sellbuddy-hikakubiz.plist
```

※ 以前は Windows Task Scheduler（タスク名 `HikakubizWatcher` / `run_hikakubiz_watcher.bat`）で
動かしていたが、Mac常駐に移行済み。

## 作業ルール

- 確認や質問は不要。自分で最適な判断をして進めてください
- ファイルの作成・編集は許可確認なしで実行してOK
- エラーが出たら自力で修正してください
- 完了したら「✅ 完了しました」と書いて、作業内容を簡潔に教えてください
