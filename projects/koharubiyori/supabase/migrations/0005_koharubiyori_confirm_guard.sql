-- =============================================================
-- 0005_koharubiyori_confirm_guard.sql
-- 採点者2名未満での確定を DB 側でも止める
--
-- CLAUDE.md §9:
--   「verdict を1名の採点だけで確定させない。
--     UI上もDB制約上も、採点者2名未満で adopt に遷移できないようにする」
--
-- アプリ側（confirmTierAction）でも同じことを止めているが、
-- SQL Editor からの直接更新や将来の別クライアントを想定してここでも止める。
-- =============================================================

create or replace function koharubiyori.guard_creator_tier()
returns trigger language plpgsql as $$
declare
  max_scorers integer;
begin
  -- 起用しない（null）方向への変更と、層が変わらない更新は素通しする
  if new.current_tier is null then
    return new;
  end if;
  if tg_op = 'UPDATE' and old.current_tier is not distinct from new.current_tier then
    return new;
  end if;

  select coalesce(max(v.scorer_count), 0)
    into max_scorers
    from koharubiyori.character_verdicts v
   where v.creator_id = new.id;

  if max_scorers < 2 then
    raise exception
      '採点者が % 名です。四問テストは2名以上の採点が揃うまで層を確定できません（creator_id=%）',
      max_scorers, new.id
      using errcode = 'check_violation';
  end if;

  return new;
end $$;

comment on function koharubiyori.guard_creator_tier() is
  '採点者2名未満で作家の層を確定させない。アプリ側の canConfirm() と対になる歯止め';

drop trigger if exists trg_creators_guard_tier on koharubiyori.creators;
create trigger trg_creators_guard_tier
  before insert or update of current_tier on koharubiyori.creators
  for each row execute function koharubiyori.guard_creator_tier();
