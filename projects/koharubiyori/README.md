# 小晴日和（こはるびより）

京都・河原町の露店限定の編集レーベル。掛け紙のQR → 候の掛け紙ページ → 作家紹介ページ → 作家自身のEC、
という導線と、作家・キャラクターの採点／掛け紙の発行管理をひとつの Next.js アプリで持つ。

引き継ぎパッケージは「Phase 1 の既存リポジトリに追加実装する」前提だったが、**Phase 1 は未着手だったため、
このリポジトリを土台としてゼロから起こしている。** Phase 1 相当（物語ページ・商品導線）は後から
この構成の上に足せる。

## セットアップ

```bash
npm install
cp .env.example .env.local   # 値を埋める
npm run dev                  # http://localhost:3000
```

### Supabase

1. プロジェクトを作る（未作成なら）
2. SQL Editor で **この順に** 実行する

   | ファイル | 内容 |
   |---|---|
   | `supabase/migrations/0002_koharubiyori_creators.sql` | スキーマ・ENUM・作家・キャラクター・採点・契約・RLS |
   | `supabase/migrations/0003_koharubiyori_kakegami.sql` | 七十二候マスタ・掛け紙・スキャン計測・晴れ間だより |
   | `supabase/migrations/0005_koharubiyori_confirm_guard.sql` | 採点者2名未満での層の確定をDB側でも止める |
   | `supabase/seed/0004_koyomi_ko_seed.sql` | 七十二候72行（候のコピーは未投入。あとから入れる） |

3. **Settings → API → Exposed schemas に `koharubiyori` を追加する。**
   ここを忘れると PostgREST がスキーマを見ず、全クエリが 404 になる
4. Authentication → URL Configuration の Redirect URLs に `<本番URL>/auth/callback` を追加する
5. 型を生成し直す（テーブルを足すたび）

   ```bash
   npm run gen:types   # --schema koharubiyori 付き。付け忘れると空の型が出る
   ```

`src/types/database.ts` は生成前でも型が通るよう手書きの同等物が入っている。
マイグレーションを流したら生成コマンドで上書きすること。

### 作家画像の保存先

Supabase Storage に公開バケットを作り、バケット名を `NEXT_PUBLIC_SUPABASE_STORAGE_BUCKET` に入れる。
`next.config.ts` は `NEXT_PUBLIC_SUPABASE_URL` のホストからの
`/storage/v1/object/public/**` だけを画像として許可している。

### 管理画面の認証

Supabase Auth のメールリンク（Magic Link）＋ `ADMIN_ALLOWED_EMAILS` の突き合わせ。
許可リストが空のときは**全員拒否**になる（未設定のまま公開して誰でも入れる事故を避けるため）。
`src/proxy.ts` と各ページの `getAdminUser()` の二段で止めている。

## 画面

| パス | 誰が見る | 内容 |
|---|---|---|
| `/` | 来店者 | ブランド定義といまの候 |
| `/sakka` `/sakka/[slug]` | 来店者 | 作家紹介。`status=published` 以外は404 |
| `/kakegami` `/kakegami/[ko]` | 来店者 | 七十二候一覧と、候の掛け紙 |
| `/qr/[kakegami_id]` | 来店者 | 掛け紙裏QRの着地点。スキャンを記録して候ページへ転送 |
| `/admin/creators` | 運営 | 一覧（合計点の降順）・登録・編集・四問テスト採点 |
| `/admin/kakegami` | 運営 | 発行管理とスキャン率 |

## コマンド

```bash
npm run dev        # 開発サーバー
npm run build      # 本番ビルド
npm run typecheck  # tsc --noEmit
npm run lint       # eslint
npm run check      # 四問テストとJST日付のロジック検証
npm run gen:types  # Supabase から型を生成
```

## 未着手（TASKS.md 参照）

Phase 2-3（契約管理・晴れ間だより号・作家別ダッシュボード）と、Phase 1 相当の物語ページ。
