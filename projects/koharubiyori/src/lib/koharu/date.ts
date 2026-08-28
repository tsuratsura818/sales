/**
 * 日付は**すべて JST で扱う**。
 * 露店は毎週水曜、候は5日単位で切り替わる。UTC のまま日付比較すると
 * 候の切り替わりが9時間ずれて前日の掛け紙が出る（CLAUDE.md §9）。
 */

const JST_TIME_ZONE = 'Asia/Tokyo'

const ymdFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: JST_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

const displayFormatter = new Intl.DateTimeFormat('ja-JP', {
  timeZone: JST_TIME_ZONE,
  year: 'numeric',
  month: 'long',
  day: 'numeric',
})

/** JST の 'YYYY-MM-DD' */
export function jstYmd(date: Date = new Date()): string {
  return ymdFormatter.format(date)
}

/** JST の 'MM-DD'。七十二候マスタの starts_md と突き合わせる形 */
export function jstMonthDay(date: Date = new Date()): string {
  return jstYmd(date).slice(5)
}

/** date 列（'YYYY-MM-DD'）の表示。タイムゾーン変換を挟まず素直に組む */
export function formatJaDate(ymd: string | null): string {
  if (!ymd) return '—'
  const [y, m, d] = ymd.split('-')
  if (!y || !m || !d) return ymd
  return `${Number(y)}年${Number(m)}月${Number(d)}日`
}

/** timestamptz の表示を JST に寄せる */
export function formatJaDateTime(iso: string | null): string {
  if (!iso) return '—'
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return iso
  return displayFormatter.format(parsed)
}

/**
 * その日にあたる候を、七十二候マスタから選ぶ。
 *
 * starts_md は 'MM-DD' の文字列。1月の候（01-05 〜 01-30）は
 * 文字列順で先頭に来るが、暦の並びでは立春(02-04)始まりの最後尾にあたる。
 * 「今日以下で最大の starts_md」を採ればどちらの期間でも正しい候が出る。
 * 1/1〜1/4 だけは該当がないので、前年の最後の候（12-31）に落とす。
 */
export function pickKoForDate<T extends { starts_md: string }>(
  koList: readonly T[],
  date: Date = new Date(),
): T | null {
  if (koList.length === 0) return null
  const today = jstMonthDay(date)

  let best: T | null = null
  let fallback: T | null = null

  for (const ko of koList) {
    if (fallback === null || ko.starts_md > fallback.starts_md) fallback = ko
    if (ko.starts_md <= today && (best === null || ko.starts_md > best.starts_md)) best = ko
  }

  return best ?? fallback
}
