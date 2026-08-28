import type { Enums } from '@/types/database'

/**
 * 四問テストの判定ロジック。
 *
 * ★ DB 側のビュー koharubiyori.character_verdicts と必ず同じ結果になること。
 *   片方だけ直すと判定がずれる。
 *
 * 判定順は仕様であってバグではない（CLAUDE.md §6）:
 *   合計点より先に「暦（q3）0点」の足切りを評価する。
 */

export const MAX_PER_QUESTION = 5
export const MAX_TOTAL = 20

export type ScoreInput = {
  q1_line: number
  q2_kurashi: number
  q3_koyomi: number
  q4_taigi: number
}

export type Verdict = Enums<'score_verdict'>

export function totalOf(score: ScoreInput): number {
  return score.q1_line + score.q2_kurashi + score.q3_koyomi + score.q4_taigi
}

/**
 * 採点1件から判定する。単票のプレビュー用。
 * 確定判定は必ず judgeAll()（採点者全員ぶん）を使うこと。
 */
export function judgeOne(score: ScoreInput): Verdict {
  return judgeFrom(totalOf(score), score.q3_koyomi)
}

/**
 * 採点者全員ぶんから判定する。DB ビューと同じ規則:
 *   - 足切り: **1人でも** 暦に0点を付けたら reject
 *   - 合計は採点者の平均で見る
 */
export function judgeAll(scores: readonly ScoreInput[]): {
  scorerCount: number
  avgTotal: number | null
  minQ3: number | null
  verdict: Verdict | null
  /** 採点者2名未満は確定させない（CLAUDE.md §9） */
  isConfirmable: boolean
} {
  if (scores.length === 0) {
    return { scorerCount: 0, avgTotal: null, minQ3: null, verdict: null, isConfirmable: false }
  }

  const totals = scores.map(totalOf)
  const avgTotal = round1(totals.reduce((a, b) => a + b, 0) / scores.length)
  const minQ3 = Math.min(...scores.map((s) => s.q3_koyomi))

  return {
    scorerCount: scores.length,
    avgTotal,
    minQ3,
    verdict: judgeFrom(avgTotal, minQ3),
    isConfirmable: scores.length >= 2,
  }
}

/** 足切り → 合計点、の順で評価する。この順序を入れ替えないこと */
function judgeFrom(total: number, q3: number): Verdict {
  if (q3 === 0) return 'reject'
  if (total >= 16) return 'adopt'
  if (total >= 12) return 'trial'
  if (total >= 8) return 'hold'
  return 'reject'
}

/**
 * 判定を確定（= creators.current_tier を動かす）してよいか。
 * adopt は採点者2名以上を必須にする。DB 制約と UI の両方で止める。
 */
export function canConfirm(verdict: Verdict | null, scorerCount: number): boolean {
  if (verdict === null) return false
  if (verdict === 'adopt') return scorerCount >= 2
  return scorerCount >= 2
}

/** 自動判定が示す層。adopt は層二から入る（CLAUDE.md §6） */
export function tierForVerdict(verdict: Verdict | null): Enums<'creator_tier'> | null {
  if (verdict === 'adopt') return 'tier2'
  if (verdict === 'trial') return 'tier1'
  return null
}

export function isValidScore(value: number): boolean {
  return Number.isInteger(value) && value >= 0 && value <= MAX_PER_QUESTION
}

function round1(n: number): number {
  return Math.round(n * 10) / 10
}
