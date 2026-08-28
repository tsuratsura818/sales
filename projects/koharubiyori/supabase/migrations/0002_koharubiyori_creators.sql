-- =============================================================
-- 0002_koharubiyori_creators.sql
-- 小晴日和 Phase 2: 作家・キャラクター・四問テスト採点・契約
-- 冪等: 再実行しても壊れない構成にしてある
-- 前提: schema "koharubiyori" は Phase 1 で作成済み
-- =============================================================

create schema if not exists koharubiyori;

-- -------------------------------------------------------------
-- ENUM 型
-- -------------------------------------------------------------

-- 六つの晴れ間（ブランド固有。横展開時はここを差し替える）
do $$ begin
  create type koharubiyori.hare_ma as enum (
    'asa',        -- 朝の晴れ間
    'hitoiki',    -- ひと息の晴れ間
    'yoru',       -- 夜の晴れ間
    'dekakeru',   -- 出かける晴れ間
    'kazaru',     -- 飾る晴れ間
    'sodateru'    -- 育てる晴れ間（レザー参画時に追加）
  );
exception when duplicate_object then null; end $$;

-- 参画の三層
do $$ begin
  create type koharubiyori.creator_tier as enum (
    'tier1',  -- 客人（まろうど）: 晴れ間だより誌面のみ
    'tier2',  -- 候の描き手: 掛け紙の描き下ろし
    'tier3'   -- 晴れ間の仲間: 商品化
  );
exception when duplicate_object then null; end $$;

-- 四問テストの判定
do $$ begin
  create type koharubiyori.score_verdict as enum (
    'adopt',   -- 16-20点: 採用（層二から入る）
    'trial',   -- 12-15点: 試す（層一で様子を見る）
    'hold',    -- 8-11点 : 保留（半年後に再評価）
    'reject'   -- 0-7点 または 第三問=0の足切り
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type koharubiyori.publish_status as enum ('draft', 'published', 'archived');
exception when duplicate_object then null; end $$;

-- -------------------------------------------------------------
-- updated_at トリガー関数
-- -------------------------------------------------------------
create or replace function koharubiyori.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- -------------------------------------------------------------
-- creators : 作家（描き手・作り手）
-- -------------------------------------------------------------
create table if not exists koharubiyori.creators (
  id            uuid primary key default gen_random_uuid(),
  slug          text not null unique,             -- /sakka/[slug]
  name          text not null,                    -- 表記名（漢字等）
  name_kana     text,                             -- よみ
  title         text,                             -- 肩書「絵の描き手」「革の作り手」
  base_area     text,                             -- 拠点「京都・伏見」
  profile       text,                             -- 200〜400字。運営が書く
  tsukumo_note  text,                             -- 編集長ツクモによる紹介文（1〜2行）
  photo_url     text,
  hero_image_url text,
  sns_x         text,
  sns_instagram text,
  website_url   text,
  ec_url        text,                             -- 作家自身のEC（送客先）
  current_tier  koharubiyori.creator_tier,        -- 現在の層。未起用は null
  status        koharubiyori.publish_status not null default 'draft',
  first_engaged_on date,
  notes         text,                             -- 社内メモ（非公開）
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

comment on table koharubiyori.creators is '小晴日和に参画する作家。status=published のみ /sakka/[slug] で公開される';
comment on column koharubiyori.creators.ec_url is '作家自身のEC。掛け紙QR→作家ページ→ここへ送客するのが参画メリットの実体';

create index if not exists idx_creators_status on koharubiyori.creators (status);
create index if not exists idx_creators_tier   on koharubiyori.creators (current_tier);

drop trigger if exists trg_creators_updated_at on koharubiyori.creators;
create trigger trg_creators_updated_at before update on koharubiyori.creators
  for each row execute function koharubiyori.set_updated_at();

-- -------------------------------------------------------------
-- characters : キャラクター（1作家に複数あり得る）
-- -------------------------------------------------------------
create table if not exists koharubiyori.characters (
  id            uuid primary key default gen_random_uuid(),
  creator_id    uuid not null references koharubiyori.creators(id) on delete cascade,
  slug          text not null unique,
  name          text not null,
  description   text,
  hare_ma       koharubiyori.hare_ma,             -- どの晴れ間に住むか。必ず1つに定める
  image_url     text,
  status        koharubiyori.publish_status not null default 'draft',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

comment on column koharubiyori.characters.hare_ma is
  '大原則・壱「編集軸が先、キャラクターが後」。六つの晴れ間に翻訳できないキャラクターは登録しない';

create index if not exists idx_characters_creator on koharubiyori.characters (creator_id);
create index if not exists idx_characters_hare_ma on koharubiyori.characters (hare_ma);

drop trigger if exists trg_characters_updated_at on koharubiyori.characters;
create trigger trg_characters_updated_at before update on koharubiyori.characters
  for each row execute function koharubiyori.set_updated_at();

-- -------------------------------------------------------------
-- character_scores : 四問テストの採点（採点者ごとに1行）
-- -------------------------------------------------------------
create table if not exists koharubiyori.character_scores (
  id            uuid primary key default gen_random_uuid(),
  character_id  uuid not null references koharubiyori.characters(id) on delete cascade,
  scorer_name   text not null,                    -- 採点者。2名以上必須（アプリ側で担保）
  q1_line       smallint not null check (q1_line     between 0 and 5), -- 一・線（紙に置けるか）
  q2_kurashi    smallint not null check (q2_kurashi  between 0 and 5), -- 二・暮らし（物語があるか）
  q3_koyomi     smallint not null check (q3_koyomi   between 0 and 5), -- 三・暦（季節に翻訳できるか）★足切り
  q4_taigi      smallint not null check (q4_taigi    between 0 and 5), -- 四・大義（作り手の側の人か）
  total         smallint generated always as (q1_line + q2_kurashi + q3_koyomi + q4_taigi) stored,
  comment       text,
  scored_at     timestamptz not null default now(),
  unique (character_id, scorer_name)
);

comment on column koharubiyori.character_scores.q3_koyomi is
  '足切り項目。0点なら他が満点でも不採用。判定は合計点より先に q3=0 を評価すること（仕様）';

create index if not exists idx_scores_character on koharubiyori.character_scores (character_id);

-- 判定ビュー: 採点者の平均で判定する。足切りは「1人でも0を付けたら reject」
create or replace view koharubiyori.character_verdicts as
select
  c.id                                as character_id,
  c.creator_id,
  count(s.id)                         as scorer_count,
  round(avg(s.total)::numeric, 1)     as avg_total,
  min(s.q3_koyomi)                    as min_q3,
  case
    when count(s.id) = 0            then null
    when min(s.q3_koyomi) = 0       then 'reject'::koharubiyori.score_verdict
    when avg(s.total) >= 16         then 'adopt'::koharubiyori.score_verdict
    when avg(s.total) >= 12         then 'trial'::koharubiyori.score_verdict
    when avg(s.total) >= 8          then 'hold'::koharubiyori.score_verdict
    else 'reject'::koharubiyori.score_verdict
  end                                 as verdict,
  (count(s.id) >= 2)                  as is_confirmable   -- 採点者2名未満は確定させない
from koharubiyori.characters c
left join koharubiyori.character_scores s on s.character_id = c.id
group by c.id, c.creator_id;

comment on view koharubiyori.character_verdicts is
  'アプリ側の scoring.ts と必ず同じロジックにすること。片方だけ直すと判定がずれる';

-- -------------------------------------------------------------
-- contracts : 契約（層ごとに条件が変わる）
-- -------------------------------------------------------------
create table if not exists koharubiyori.contracts (
  id                    uuid primary key default gen_random_uuid(),
  creator_id            uuid not null references koharubiyori.creators(id) on delete restrict,
  tier                  koharubiyori.creator_tier not null,
  scope                 text not null,            -- 使用範囲。包括表現を使わず具体的に書く
  color_adjust_allowed  boolean not null default true,  -- 掛け紙仕様に合わせた色調整の可否（世界観維持の生命線）
  is_exclusive          boolean not null default false, -- 原則 非独占
  ai_training_prohibited boolean not null default true, -- 学習利用は行わない旨を明記
  fee_yen               integer,                  -- 原稿料
  revenue_share_pct     numeric(4,1),             -- 層三のみ。卸価格の8〜12%を想定
  starts_on             date not null,
  ends_on               date,
  doc_url               text,                     -- 契約書PDFの保管先
  notes                 text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  check (ends_on is null or ends_on >= starts_on)
);

comment on column koharubiyori.contracts.ai_training_prohibited is
  'true が既定。作家の作品画像を外部AI APIに投げる処理を実装しないこと（CLAUDE.md §9）';

create index if not exists idx_contracts_creator on koharubiyori.contracts (creator_id);
create index if not exists idx_contracts_ends_on on koharubiyori.contracts (ends_on);

drop trigger if exists trg_contracts_updated_at on koharubiyori.contracts;
create trigger trg_contracts_updated_at before update on koharubiyori.contracts
  for each row execute function koharubiyori.set_updated_at();

-- -------------------------------------------------------------
-- RLS
-- 公開: published のみ anon が読める
-- 書き込み: authenticated（管理者）のみ。運用開始時に core のロール判定へ差し替える
-- -------------------------------------------------------------
alter table koharubiyori.creators         enable row level security;
alter table koharubiyori.characters       enable row level security;
alter table koharubiyori.character_scores enable row level security;
alter table koharubiyori.contracts        enable row level security;

drop policy if exists creators_read_published on koharubiyori.creators;
create policy creators_read_published on koharubiyori.creators
  for select to anon, authenticated using (status = 'published');

drop policy if exists creators_write_staff on koharubiyori.creators;
create policy creators_write_staff on koharubiyori.creators
  for all to authenticated using (true) with check (true);

drop policy if exists characters_read_published on koharubiyori.characters;
create policy characters_read_published on koharubiyori.characters
  for select to anon, authenticated using (status = 'published');

drop policy if exists characters_write_staff on koharubiyori.characters;
create policy characters_write_staff on koharubiyori.characters
  for all to authenticated using (true) with check (true);

-- 採点と契約は社内情報。anon には一切見せない
drop policy if exists scores_staff_only on koharubiyori.character_scores;
create policy scores_staff_only on koharubiyori.character_scores
  for all to authenticated using (true) with check (true);

drop policy if exists contracts_staff_only on koharubiyori.contracts;
create policy contracts_staff_only on koharubiyori.contracts
  for all to authenticated using (true) with check (true);

grant usage on schema koharubiyori to anon, authenticated;
grant select on koharubiyori.creators, koharubiyori.characters to anon, authenticated;
grant all    on koharubiyori.creators, koharubiyori.characters,
                koharubiyori.character_scores, koharubiyori.contracts to authenticated;
grant select on koharubiyori.character_verdicts to authenticated;
