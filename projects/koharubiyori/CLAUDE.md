# CLAUDE.md — 小晴日和 作家・掛け紙管理システム

> このドキュメントだけ読めば作業を続けられる状態にしてある。
>
> **引き継ぎ時の前提が変わっている。** 元のパッケージは「既存の Phase 1（QR物語基盤）への追加実装」
> という前提だったが、**Phase 1 は未着手だったため、このリポジトリを土台としてゼロから起こした。**
> Phase 2-1 と 2-2 の範囲（作家・採点・掛け紙・スキャン計測）は実装済み。
> Phase 1 相当（物語ページ・商品導線）は、この構成の上に後から足す。
> 実装状況は TASKS.md、セットアップ手順は README.md を見ること。

---

## 1. プロジェクト概要

### 何をつくるか

小晴日和（こはるびより）は、京都・河原町の店舗軒先に毎週水曜に出店する**露店限定の編集レーベル**。TSURATSURAの複数事業の商品を「六つの晴れ間」という軸で再編集して販売する。

導線の骨格は **掛け紙のQR → 候の掛け紙ページ → 作家紹介ページ → 作家自身のEC**。
（当初 Phase 1 とされていた「物語ページ → 各ブランドEC」はまだ無い。後から足す）

いま載っているのは**外部クリエイター（絵の描き手）の参画**まわりの次の4つ。

| # | つくるもの | 誰のため |
|---|---|---|
| A | 作家紹介ページ `/sakka/[slug]` | 来店者。掛け紙裏QRの着地点 |
| B | 候の掛け紙ページ `/kakegami/[ko]` | 来店者。その候の掛け紙の解説と作家への導線 |
| C | 作家・キャラクターの管理と採点（管理画面） | 運営（西川） |
| D | 掛け紙の発行管理とスキャン計測 | 運営（西川） |

### ビジネス目標

- 掛け紙裏QRの**スキャン率 15%以上**（配布枚数に対する）
- 作家紹介ページから**作家自身のSNS/ECへの送客**を成立させる（＝作家にとっての参加メリット。口説き文句そのもの）
- 年間で**採点済み作家20〜30名**のデータベースを構築する。これが百貨店催事での提案力の原資になる

### 参照ドキュメント（人間用・Claude Codeは読まなくてよい）

`docs/小晴日和_キャラクター参画設計書_v1.html` に、選定基準・三層構造・契約条件の根拠がある。**実装判断に必要な情報はすべて本CLAUDE.mdに転記済み**。

---

## 2. 技術構成

**新しい依存を増やさない。** 追加してよいのは、この表の枠内に収まらない機能が本当に必要になったときだけ。

| 領域 | 採用 | 理由 |
|---|---|---|
| フレームワーク | Next.js 16 (App Router) / React 19 | — |
| 言語 | TypeScript（strict） | — |
| スタイル | Tailwind v4（素の CSS とユーティリティのみ。UIライブラリは入れていない） | — |
| DB | Supabase（Postgres） | **スキーマは `koharubiyori`** |
| ホスティング | Vercel | — |

### 使わないもの

- **状態管理ライブラリを入れない**（Zustand / Redux 等）。Server Components + URL状態で足りる
- **ORMを追加しない**。Supabase JS クライアントの型生成（`supabase gen types`）で足りる
- 画像最適化に外部SaaSを使わない。Supabase Storage + `next/image` で完結させる

---

## 3. 開発環境セットアップ

```bash
npm install
cp .env.example .env.local        # 値を埋める
npm run dev
```

Supabase 側の手順（Exposed schemas の追加を含む）と、マイグレーションの適用順は
**README.md に集約してある**。型生成は毎回これ:

```bash
npm run gen:types   # = supabase gen types typescript --schema koharubiyori > src/types/database.ts
```

検証:

```bash
npm run typecheck   # tsc --noEmit
npm run lint        # eslint
npm run check       # 四問テストの判定とJSTの候切り替わりを検証する
npm run build
```

## 4. ディレクトリ構成

```
src/
├── proxy.ts                          管理画面のガード（Next.js 16 で middleware から改称）
├── app/
│   ├── page.tsx                      トップ（ブランド定義といまの候）
│   ├── robots.ts / sitemap.ts
│   ├── sakka/page.tsx                作家一覧
│   ├── sakka/[slug]/page.tsx         A: 作家紹介ページ
│   ├── kakegami/page.tsx             七十二候の一覧
│   ├── kakegami/[ko]/page.tsx        B: 候の掛け紙ページ
│   ├── qr/[id]/route.ts              掛け紙裏QRの着地点。スキャンを記録して転送
│   ├── auth/callback/route.ts        メールリンクの着地点
│   └── admin/
│       ├── login/page.tsx
│       ├── page.tsx                  ダッシュボード
│       ├── creators/{page,new,[id]}  C: 一覧・登録・編集＋採点
│       ├── creators/actions.ts       サーバーアクション
│       └── kakegami/{page,new}       D: 発行管理・発行登録
│           └── actions.ts
├── components/koharu/
│   ├── creator-profile.tsx
│   ├── creator-form.tsx
│   ├── score-sheet.tsx               四問テストの採点フォーム（唯一の 'use client'）
│   ├── hare-ma-badge.tsx
│   ├── kakegami-card.tsx
│   └── json-ld.tsx
├── lib/
│   ├── koharu/{constants,scoring,date,queries}.ts
│   ├── supabase/server.ts
│   ├── auth.ts
│   └── site.ts                       絶対URLとQRのURLスキーム
└── types/database.ts                 生成物。手で編集しない

supabase/
├── migrations/0002_koharubiyori_creators.sql
├── migrations/0003_koharubiyori_kakegami.sql
├── migrations/0005_koharubiyori_confirm_guard.sql
└── seed/0004_koyomi_ko_seed.sql      七十二候72行（copy は未投入）

scripts/check-logic.ts                受け入れ基準のうちロジックで確かめられるもの
```

## 5. デザイン仕様

**デザイントークンは固定。** 新しい色を足さない。

トークンの定義場所: `src/app/globals.css` の `@theme` ブロック。ここが唯一の正。

| 用途 | トークン | 値 |
|---|---|---|
| 地 | `--washi` | `#FBF7EF`（生成り） |
| 文字 | `--sumi` | `#23201C`（墨） |
| 差し色 | `--hare` | `#C8873A`（陽だまり） |
| 罫 | `--line` | `#DDD3C2` |

- 見出しは明朝、本文はゴシック。日本語組版は `font-feature-settings: "palt" 1` / `line-height: 1.8` / 見出しに `word-break: keep-all`
- **作家の作品画像は、ページの中で最も大きい要素にしてよい**。作家紹介ページに限り、絵が主役になる（店頭・商品では逆。§9参照）
- 画像は `object-fit: cover`、`width`/`height` 必須（CLS対策）

---

## 6. 機能・画面仕様

### A. 作家紹介ページ `/sakka/[slug]`

掛け紙裏のQRから来る。**滞在30秒で「この人から買った」と思える**ことがゴール。

| 要素 | 内容 |
|---|---|
| ヘッダー | 作家名（漢字＋かな）／肩書（例：絵の描き手・革の作り手）／拠点 |
| 主画像 | その作家の代表作 or 掛け紙原画 |
| プロフィール | 200〜400字。運営が書く（作家の自己紹介文をそのまま載せない） |
| この作家が描いた掛け紙 | `kakegami` を新しい順に。候名・日付・画像。各々 `/kakegami/[ko]` へ |
| 晴れ間バッジ | 担当した晴れ間（六つのうち） |
| 外部リンク | 作家のSNS・EC・個展情報。**`rel="noopener"` + 外部遷移の明示** |
| ツクモの一言 | 編集長ツクモによる紹介文（1〜2行、固定枠） |

- `status = 'published'` のみ表示。それ以外は 404
- 構造化データ: `Person`（作家）＋ `BreadcrumbList`
- OGP: 作家名 + 掛け紙画像

### B. 候の掛け紙ページ `/kakegami/[ko]`

`[ko]` は候のスラッグ（例: `kusa-no-tsuyu-shiroshi`）。

| 要素 | 内容 |
|---|---|
| 候名・読み・期間 | 七十二候マスタから |
| 候のコピー | `koyomi_ko.copy`。**72本まだ未執筆**。入るまでこの行は出ない |
| 掛け紙の絵 | その候の掛け紙画像 |
| 描き手 | 作家名 → `/sakka/[slug]` へ |
| その日の商品 | 物語ページへの導線（**未実装**。物語ページを作ったら足す） |

### C. 管理画面 `/admin/creators`

- 一覧: 名前・層（Tier 1/2/3）・合計点・判定・最終起用日。**合計点で降順ソートできること**
- 採点フォーム（`score-sheet.tsx`）: 四問を各0〜5点で入力。**採点者は2名以上を必須**（1名だけの状態で `verdict` を確定させない）
- 判定は自動計算（§ scoring ロジック）。手動上書きは可、ただし理由コメント必須

### D. 掛け紙の発行管理 `/admin/kakegami`

- 候・作家・発行日・刷り部数・配布実績を登録
- スキャン数を表示（`kakegami_scans` の集計）
- **スキャン率 = scans / distributed_qty** を一覧に出す。これが層二→層三の昇格判断に直結する

### 採点ロジック（`lib/koharu/scoring.ts`）

```
合計 = q1_line + q2_kurashi + q3_koyomi + q4_taigi   （各 0〜5、満点20）

if (q3_koyomi === 0) return 'reject'     ← 足切り。他が満点でも不採用
if (total >= 16) return 'adopt'          採用（層二から入る）
if (total >= 12) return 'trial'          試す（層一で様子を見る）
if (total >= 8)  return 'hold'           保留（半年後に再評価）
return 'reject'                          見送る
```

**足切りの判定順を変えないこと。** 合計点より先に `q3 === 0` を評価する。これは仕様であってバグではない。

### 構造化データ・AEO（必須）

後から差し込むと作り直しになるため、初回実装で入れる。

- `/sakka/[slug]` に `Person`、トップに `Organization`、全ページに `BreadcrumbList`
- 文中の定義構文を統一する: **「小晴日和は、京都・河原町の露店限定の編集レーベルです。」**
- `robots.txt` でAIクローラー（GPTBot / ClaudeBot / PerplexityBot 等）を**許可**する

---

## 7. 実装の優先順位

Phase 2-1 と Phase 2-2 は**実装済み**。細かい進捗は TASKS.md を見ること。

### Phase 2-3（未着手）

- [ ] 契約管理（`contracts`）の登録・期限アラート
- [ ] 『晴れ間だより』号管理（`paper_issues`）と客人アサイン
- [ ] 作家別ダッシュボード（スキャン率・掛け紙枚数・昇格提案）

### Phase 3（横展開・設計だけ意識しておく）

作家DBと採点の仕組みは**小晴日和固有ではない**。TSURATSURAの他ブランド（tabirou / いとをかし / Komapara）でも「クリエイターを選定して起用する」構造は同じ。
**`koharubiyori` スキーマに閉じた実装にしつつ、テーブル定義とスコアリングは他スキーマへコピーできる粒度に保つ**こと。ブランド固有の語（晴れ間・候）はENUMとマスタテーブルに追い出してあるので、そこを差し替えれば移植できる。

---

## 8. コーディング規約

- コンポーネントは `PascalCase`、ファイルは `kebab-case.tsx`
- Supabaseクエリは**必ず `lib/koharu/queries.ts` に集約**。ページから直接 `supabase.from()` を呼ばない
- `any` 禁止。型は `src/types/database.ts` の生成型から派生させる
- Server Components をデフォルトに。`'use client'` は採点フォームなど入力を伴うものだけ
- コミットメッセージ: `feat(koharu): 作家紹介ページを追加` の形式

---

## 9. 注意事項・制約 ★最重要

### やってはいけないこと

- **既存のマイグレーションを書き換えない。** 変更は必ず新しい番号のファイルを足す形で行う。適用済みのSQLを直すと、環境ごとにスキーマがずれる
- **`public` スキーマにテーブルを作らない。** TSURATSURAは「core + ブランドごとのスキーマ」構成。必ず `koharubiyori` スキーマに作る
- **`/qr/[kakegami_id]` のURLスキームを変更しない。** 掛け紙は日付入りで刷られる。一度配布したらURLは変えられず、変えると過去の掛け紙が全部404になる。**印刷物は回収できない。** 新しいページを足すのはよいが、このパスは触らない
- **本番ドメインを決めてから刷る。** `NEXT_PUBLIC_SITE_URL` がQRに焼き付く
- **作家の作品画像を、AI学習用途に転用する処理を書かない。** 契約で「学習利用は行わない」と明記して作家と合意している。画像を外部AI APIに投げる処理（自動タグ付け等）を良かれと思って追加しないこと
- **`verdict` を1名の採点だけで確定させない。** UI上もDB制約上も、採点者2名未満で `adopt` に遷移できないようにする
- **商品ページ側でキャラクターを主役にしない。** ブランド原則として、キャラクターの掲出は掛け紙・タグ・作家ページに限定している。商品一覧のサムネイルをキャラクター画像に差し替えるような実装をしない

### 既知の癖・地雷

- **Supabaseの型生成は `--schema koharubiyori` を付け忘れると `public` だけを見て空の型を吐く。** `npm run gen:types` を使うこと
- **Supabase の Exposed schemas に `koharubiyori` を足し忘れると、全クエリが 404 になる。** Settings → API で追加する
- **`src/types/database.ts` の `Relationships` を空にすると、埋め込みクエリ（`select('*, ko:koyomi_ko(*)')`）の型が壊れる。** 生成物をそのまま使えば入る
- **`'use server'` のファイルからは async 関数しか export できない。** 同期のヘルパーは `lib/` 側に置く
- 掛け紙のスラッグに使う候名は**ローマ字表記に揺れがある**（例: `kusa-no-tsuyu-shiroshi` / `kusanotsuyushiroshi`）。マスタの `slug` 列を唯一の正とし、コード内でローマ字を組み立てない
- 日付は**すべて JST で扱う**。露店は毎週水曜、候は5日単位で切り替わる。UTC保存のまま日付比較すると、候の切り替わりが9時間ずれて前日の掛け紙が表示される
- Next.js 16 の App Router で `params` は Promise。`const { slug } = await params` の形で受ける
- Next.js 16 で `middleware.ts` は `proxy.ts` に改称された。export する関数名も `proxy`

### 決着済み（当初「西川へ確認が必要」とされていた3点）

1. **作家画像の保存先** — Supabase Storage の公開バケット。バケット名は
   `NEXT_PUBLIC_SUPABASE_STORAGE_BUCKET` に入れる。`next.config.ts` は
   `NEXT_PUBLIC_SUPABASE_URL` のホストの `/storage/v1/object/public/**` だけを許可している
2. **管理画面の認証** — Phase 1 が無いので新規に実装した。Supabase Auth のメールリンク ＋
   `ADMIN_ALLOWED_EMAILS` の突き合わせ。許可リストが**空のときは全員拒否**。
   `src/proxy.ts` と各ページの `getAdminUser()` の二段で止める。
   運用が固まったら `core` スキーマのロール判定に差し替える
3. **七十二候マスタ** — Phase 1 が無いので `koharubiyori.koyomi_ko` を 0003 で新規に作り、
   0004 で72行を投入する。**候のコピー72本はまだ書かれていない**（`copy` 列が null）。
   seed を再実行しても `copy` は上書きされない作りにしてある

### いま残っている宿題

- 候のコピー72本の執筆と投入
- 本番ドメインの確定（**掛け紙を刷る前に**。`/qr/[kakegami_id]` は後から変えられない）
- Phase 2-3（契約管理・晴れ間だより号・作家別ダッシュボード）

## 10. 受け入れ基準（これが満たされたら「完成」）

ロジックで確かめられるぶんは `npm run check` が検証している（足切り・2名未満の確定不可・
JSTの候切り替わり）。実データとデプロイが要るものは TASKS.md 側で追う。

- [ ] 作家を新規登録し、2名で採点し、判定が自動で出る
- [ ] `q3_koyomi = 0` の作家は、他が満点でも `reject` になる
- [ ] 公開した作家の `/sakka/[slug]` がブラウザで表示され、外部SNSリンクが機能する
- [ ] 未公開の作家の `/sakka/[slug]` が 404 を返す
- [ ] 掛け紙を登録し、スキャン率が一覧に表示される
- [ ] `Person` / `Organization` / `BreadcrumbList` の JSON-LD が出力されている
- [ ] Lighthouse: LCP < 2.5s / CLS < 0.1（作家ページ、モバイル）
- [ ] 375px幅で全画面が破綻しない
- [ ] 掛け紙QR（`/qr/[id]`）がスキャンを記録して候ページへ転送する
