# TASKS.md — 小晴日和 実装タスク

## 済み

### 土台（Phase 1 が未着手だったため新規に起こした）

- [x] Next.js 16 (App Router) / React 19 / TypeScript strict / Tailwind v4 のプロジェクト
- [x] デザイントークン（washi / sumi / hare / line）と日本語組版の下地
- [x] Supabase クライアント（`koharubiyori` スキーマ固定）とサービスロール用クライアント
- [x] 管理画面の認証（Supabase Auth メールリンク ＋ 許可メール。proxy と各ページの二段で止める）

### Phase 2-1

- [x] 七十二候マスタのテーブル名を確定（`koharubiyori.koyomi_ko`。0003 のFKはそのまま）
- [x] `0002` / `0003` マイグレーション
- [x] `0005` 採点者2名未満で層を確定できないDB側の歯止め
- [x] `0004` 七十二候72行の seed（**候のコピーは未投入**）
- [x] `src/types/database.ts`（生成前でも通る手書き版。適用後は `npm run gen:types` で上書き）
- [x] `lib/koharu/constants.ts`（晴れ間・層・判定・四問のラベル）
- [x] `lib/koharu/scoring.ts`（**q3=0 の足切りを合計点より先に評価**）
- [x] `lib/koharu/date.ts`（JST。候の切り替わりが9時間ずれる事故を防ぐ）
- [x] `lib/koharu/queries.ts`（Supabaseクエリを集約。ページから直接呼ばない）
- [x] `/admin/creators` 一覧（合計点の降順）
- [x] `/admin/creators/new` 新規登録
- [x] `/admin/creators/[id]` 編集＋キャラクター追加＋採点フォーム
- [x] 判定の確定（採点者2名未満は不可／自動判定と違う層にするなら理由コメント必須）
- [x] `/sakka/[slug]` 作家紹介ページ（published のみ、それ以外は404）
- [x] `Person` / `Organization` / `BreadcrumbList` の JSON-LD
- [x] `robots.txt` でAIクローラーを許可、`sitemap.xml`

### Phase 2-2

- [x] `/admin/kakegami` 発行管理（候・作家・発行日・刷り部数・配布実績）
- [x] `/kakegami/[ko]` 候の掛け紙ページ
- [x] `/qr/[id]` スキャン記録エンドポイント（`kakegami_scans` へ INSERT → 候ページへ転送）
- [x] 管理画面にスキャン率を表示（目標15%。下回る行は差し色で出る）
- [x] 日付処理を JST に統一

## 残り

### 運用に入る前に必要

- [ ] Supabase プロジェクトを作り、マイグレーションと seed を流す
- [ ] Settings → API の Exposed schemas に `koharubiyori` を追加
- [ ] `npm run gen:types` で `src/types/database.ts` を生成し直す
- [ ] 候のコピー72本を書いて `koyomi_ko.copy` に入れる
- [ ] Storage の作家画像バケットを作り `.env.local` に入れる
- [ ] 本番ドメインを確定する（**掛け紙を刷る前に。QRのURLは後から変えられない**）
- [ ] Vercel にデプロイし、Auth の Redirect URLs に `/auth/callback` を登録

### Phase 2-3

- [ ] `/admin/contracts` 契約登録（使用範囲・色調整可否・AI学習禁止・期間）
- [ ] 契約期限アラート（`ends_on` の30日前）
- [ ] `/admin/paper` 晴れ間だより号管理と客人アサイン
- [ ] 作家別ダッシュボード（掛け紙枚数・スキャン率・昇格提案）

### Phase 1 相当（後から載せる）

- [ ] 物語ページと各ブランドECへの導線
- [ ] 商品マスタ（※商品一覧のサムネイルをキャラクター画像にしないこと）

### Phase 3

- [ ] テーブル定義とスコアリングを他ブランド（tabirou / いとをかし / Komapara）へ移植できる粒度に保つ

## 受け入れ基準

- [x] 2名で採点 → 判定が自動で出る（`npm run check` で検証）
- [x] q3=0 の作家は他が満点でも reject（同上）
- [x] 採点者1名では確定できない（UI・サーバーアクション・DBトリガーの三段）
- [x] 未公開の作家ページが 404
- [x] JSON-LD が出力されている
- [ ] published の作家ページが表示され、外部リンクが機能する ← 実データ投入後に確認
- [ ] スキャン率が一覧に出る ← 実データ投入後に確認
- [ ] LCP < 2.5s / CLS < 0.1（作家ページ・モバイル） ← 本番デプロイ後に計測
- [ ] 375px幅で破綻しない ← 実データ投入後に確認
