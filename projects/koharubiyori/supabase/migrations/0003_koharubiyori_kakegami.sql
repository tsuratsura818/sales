-- =============================================================
-- 0003_koharubiyori_kakegami.sql
-- 小晴日和 Phase 2: 掛け紙の発行管理 / QRスキャン計測 / 晴れ間だより号
--
-- ★実行前に必ず確認: 七十二候マスタのテーブル名
--   Phase 1 で候のコピー72本を投入済みのはず。テーブル名が
--   koharubiyori.koyomi_ko と異なる場合は、下の外部キー参照を
--   実際の名前に合わせてから実行すること（CLAUDE.md §9 未確定事項3）
-- =============================================================

-- -------------------------------------------------------------
-- koyomi_ko : 七十二候マスタ（Phase 1 に既にあれば作成されない）
-- -------------------------------------------------------------
create table if not exists koharubiyori.koyomi_ko (
  id          smallint primary key check (id between 1 and 72),
  slug        text not null unique,     -- 例: kusa-no-tsuyu-shiroshi。ローマ字はコードで組み立てずこの列を唯一の正とする
  name        text not null,            -- 例: 草露白
  reading     text not null,            -- 例: くさのつゆしろし
  sekki       text,                     -- 属する二十四節気。例: 白露
  starts_md   text not null,            -- 'MM-DD' 形式。年をまたぐ運用のため日付型にしない
  copy        text                      -- 候のコピー（既存72本）
);

comment on table koharubiyori.koyomi_ko is
  '七十二候。SNS・掛け紙・晴れ間だよりのすべてがこの軌道に乗る。72行の投入は Phase 1 の既存コピーから行う';

-- -------------------------------------------------------------
-- kakegami : 掛け紙の発行単位（1候 = 1描き手が原則）
-- -------------------------------------------------------------
create table if not exists koharubiyori.kakegami (
  id              uuid primary key default gen_random_uuid(),
  ko_id           smallint not null references koharubiyori.koyomi_ko(id) on delete restrict,
  creator_id      uuid references koharubiyori.creators(id) on delete set null,
  character_id    uuid references koharubiyori.characters(id) on delete set null,
  issue_date      date not null,               -- 刷った日（JSTで扱う）
  artwork_url     text,
  print_qty       integer check (print_qty >= 0),
  distributed_qty integer check (distributed_qty >= 0),
  status          koharubiyori.publish_status not null default 'draft',
  notes           text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (ko_id, issue_date)
);

comment on table koharubiyori.kakegami is
  '掛け紙。判型・書体・候名と日付の位置・墨の色は固定し、絵だけを差し替える。フォーマットを作家ごとに変えるとシリーズとして成立しなくなる';
comment on column koharubiyori.kakegami.issue_date is
  'JSTで扱うこと。UTC保存のまま日付比較すると候の切り替わりが9時間ずれる（CLAUDE.md §9）';

create index if not exists idx_kakegami_ko      on koharubiyori.kakegami (ko_id);
create index if not exists idx_kakegami_creator on koharubiyori.kakegami (creator_id);
create index if not exists idx_kakegami_date    on koharubiyori.kakegami (issue_date desc);

drop trigger if exists trg_kakegami_updated_at on koharubiyori.kakegami;
create trigger trg_kakegami_updated_at before update on koharubiyori.kakegami
  for each row execute function koharubiyori.set_updated_at();

-- -------------------------------------------------------------
-- kakegami_scans : 掛け紙裏QRのスキャン計測
-- 層二 → 層三の昇格判断がこの数字に直結する
-- -------------------------------------------------------------
create table if not exists koharubiyori.kakegami_scans (
  id           bigint generated always as identity primary key,
  kakegami_id  uuid not null references koharubiyori.kakegami(id) on delete cascade,
  scanned_at   timestamptz not null default now(),
  referrer     text,
  user_agent   text,
  country      text
);

create index if not exists idx_scans_kakegami on koharubiyori.kakegami_scans (kakegami_id, scanned_at desc);

-- スキャン率ビュー: 管理画面の一覧に出す
create or replace view koharubiyori.kakegami_stats as
select
  k.id            as kakegami_id,
  k.ko_id,
  k.issue_date,
  k.creator_id,
  k.distributed_qty,
  count(s.id)     as scan_count,
  case when coalesce(k.distributed_qty, 0) > 0
       then round(count(s.id)::numeric / k.distributed_qty * 100, 1)
       else null end as scan_rate_pct       -- 目標 15%以上
from koharubiyori.kakegami k
left join koharubiyori.kakegami_scans s on s.kakegami_id = k.id
group by k.id;

-- -------------------------------------------------------------
-- paper_issues : フリーペーパー『晴れ間だより』の号
-- 隔月・年6回・A5・16ページ / 8割読み物・2割商品
-- -------------------------------------------------------------
create table if not exists koharubiyori.paper_issues (
  id                uuid primary key default gen_random_uuid(),
  issue_no          integer not null unique,     -- 創刊号 = 1
  title             text not null,               -- 例: 白露号
  ko_id             smallint references koharubiyori.koyomi_ko(id) on delete set null,
  published_on      date,
  guest_creator_id  uuid references koharubiyori.creators(id) on delete set null, -- 層一「客人」
  feature_maker_id  uuid references koharubiyori.creators(id) on delete set null, -- 特集「作り手を訪ねて」
  cover_image_url   text,
  print_qty         integer check (print_qty >= 0),
  status            koharubiyori.publish_status not null default 'draft',
  notes             text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

comment on column koharubiyori.paper_issues.guest_creator_id is
  '層一「客人」。編集長ツクモが招いたゲストとして誌面に登場する';

drop trigger if exists trg_paper_issues_updated_at on koharubiyori.paper_issues;
create trigger trg_paper_issues_updated_at before update on koharubiyori.paper_issues
  for each row execute function koharubiyori.set_updated_at();

-- -------------------------------------------------------------
-- RLS
-- -------------------------------------------------------------
alter table koharubiyori.koyomi_ko      enable row level security;
alter table koharubiyori.kakegami       enable row level security;
alter table koharubiyori.kakegami_scans enable row level security;
alter table koharubiyori.paper_issues   enable row level security;

drop policy if exists koyomi_read_all on koharubiyori.koyomi_ko;
create policy koyomi_read_all on koharubiyori.koyomi_ko
  for select to anon, authenticated using (true);

drop policy if exists koyomi_write_staff on koharubiyori.koyomi_ko;
create policy koyomi_write_staff on koharubiyori.koyomi_ko
  for all to authenticated using (true) with check (true);

drop policy if exists kakegami_read_published on koharubiyori.kakegami;
create policy kakegami_read_published on koharubiyori.kakegami
  for select to anon, authenticated using (status = 'published');

drop policy if exists kakegami_write_staff on koharubiyori.kakegami;
create policy kakegami_write_staff on koharubiyori.kakegami
  for all to authenticated using (true) with check (true);

-- スキャンは匿名の来店者が記録する。INSERTのみ許可し、SELECTは社内のみ
drop policy if exists scans_insert_anon on koharubiyori.kakegami_scans;
create policy scans_insert_anon on koharubiyori.kakegami_scans
  for insert to anon, authenticated with check (true);

drop policy if exists scans_read_staff on koharubiyori.kakegami_scans;
create policy scans_read_staff on koharubiyori.kakegami_scans
  for select to authenticated using (true);

drop policy if exists paper_read_published on koharubiyori.paper_issues;
create policy paper_read_published on koharubiyori.paper_issues
  for select to anon, authenticated using (status = 'published');

drop policy if exists paper_write_staff on koharubiyori.paper_issues;
create policy paper_write_staff on koharubiyori.paper_issues
  for all to authenticated using (true) with check (true);

grant select on koharubiyori.koyomi_ko, koharubiyori.kakegami, koharubiyori.paper_issues
  to anon, authenticated;
grant insert on koharubiyori.kakegami_scans to anon, authenticated;
grant all    on koharubiyori.koyomi_ko, koharubiyori.kakegami,
                koharubiyori.kakegami_scans, koharubiyori.paper_issues to authenticated;
grant usage  on sequence koharubiyori.kakegami_scans_id_seq to anon, authenticated;
grant select on koharubiyori.kakegami_stats to authenticated;
