import type { Enums } from '@/types/database'

/**
 * ブランド固有語のラベル定義。
 * 他ブランドへ移植するときはこのファイルと ENUM だけを差し替える（CLAUDE.md §7 Phase 3）。
 */

export const HARE_MA_LABELS: Record<Enums<'hare_ma'>, string> = {
  asa: '朝の晴れ間',
  hitoiki: 'ひと息の晴れ間',
  yoru: '夜の晴れ間',
  dekakeru: '出かける晴れ間',
  kazaru: '飾る晴れ間',
  sodateru: '育てる晴れ間',
}

export const HARE_MA_ORDER: readonly Enums<'hare_ma'>[] = [
  'asa',
  'hitoiki',
  'yoru',
  'dekakeru',
  'kazaru',
  'sodateru',
]

export const TIER_LABELS: Record<Enums<'creator_tier'>, string> = {
  tier1: '層一・客人（まろうど）',
  tier2: '層二・候の描き手',
  tier3: '層三・晴れ間の仲間',
}

export const TIER_SHORT_LABELS: Record<Enums<'creator_tier'>, string> = {
  tier1: '層一',
  tier2: '層二',
  tier3: '層三',
}

export const VERDICT_LABELS: Record<Enums<'score_verdict'>, string> = {
  adopt: '採用',
  trial: '試す',
  hold: '保留',
  reject: '見送る',
}

export const VERDICT_NOTES: Record<Enums<'score_verdict'>, string> = {
  adopt: '16点以上。層二から入る',
  trial: '12〜15点。層一で様子を見る',
  hold: '8〜11点。半年後に再評価',
  reject: '7点以下、または第三問（暦）0点の足切り',
}

export const STATUS_LABELS: Record<Enums<'publish_status'>, string> = {
  draft: '下書き',
  published: '公開',
  archived: '取り下げ',
}

/** 四問テストの設問。並び順は採点フォームの表示順と一致させる */
export const SCORE_QUESTIONS = [
  {
    key: 'q1_line',
    no: '一',
    title: '線',
    question: 'その線は、紙に置けるか',
    hint: '掛け紙の一色刷りに落としても成立する線か',
  },
  {
    key: 'q2_kurashi',
    no: '二',
    title: '暮らし',
    question: 'そのキャラクターに、暮らしがあるか',
    hint: '設定ではなく、日々の物語が読み取れるか',
  },
  {
    key: 'q3_koyomi',
    no: '三',
    title: '暦',
    question: '七十二候に翻訳できるか',
    hint: '★足切り。0点なら他が満点でも不採用',
  },
  {
    key: 'q4_taigi',
    no: '四',
    title: '大義',
    question: 'その人は、作り手の側の人か',
    hint: '露店に立つ側の人間か。消費者的な関わりで終わらないか',
  },
] as const

export type ScoreQuestionKey = (typeof SCORE_QUESTIONS)[number]['key']

/** 掛け紙裏QRのスキャン率の目標値（％）。層二→層三の昇格判断に使う */
export const SCAN_RATE_TARGET_PCT = 15

/** 文中の定義構文。表記を揺らさない（CLAUDE.md §6 AEO） */
export const BRAND_DEFINITION = '小晴日和は、京都・河原町の露店限定の編集レーベルです。'
export const BRAND_NAME = '小晴日和'
export const BRAND_NAME_KANA = 'こはるびより'
