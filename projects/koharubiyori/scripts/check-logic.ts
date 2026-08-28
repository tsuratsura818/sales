/**
 * 受け入れ基準のうち、ロジックだけで確かめられるものを検証する。
 *   node --experimental-strip-types scripts/check-logic.ts
 */
import { judgeAll, judgeOne, tierForVerdict } from '../src/lib/koharu/scoring.ts'
import { jstMonthDay, jstYmd, pickKoForDate } from '../src/lib/koharu/date.ts'

let failed = 0
function check(label: string, actual: unknown, expected: unknown) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  if (!ok) failed++
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${ok ? '' : ` — expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`}`)
}

// --- 四問テスト -------------------------------------------------
const full = { q1_line: 5, q2_kurashi: 5, q3_koyomi: 5, q4_taigi: 5 }
const cutOff = { q1_line: 5, q2_kurashi: 5, q3_koyomi: 0, q4_taigi: 5 }

check('満点は adopt', judgeOne(full), 'adopt')
check('暦0点は他が満点でも reject（足切り）', judgeOne(cutOff), 'reject')
check('15点は trial', judgeOne({ q1_line: 5, q2_kurashi: 5, q3_koyomi: 4, q4_taigi: 1 }), 'trial')
check('11点は hold', judgeOne({ q1_line: 3, q2_kurashi: 3, q3_koyomi: 3, q4_taigi: 2 }), 'hold')
check('7点は reject', judgeOne({ q1_line: 2, q2_kurashi: 2, q3_koyomi: 2, q4_taigi: 1 }), 'reject')

check('採点者0名は判定なし・確定不可', judgeAll([]), {
  scorerCount: 0, avgTotal: null, minQ3: null, verdict: null, isConfirmable: false,
})
check('採点者1名では確定できない', judgeAll([full]).isConfirmable, false)
check('採点者2名で確定できる', judgeAll([full, full]).isConfirmable, true)
check('1人でも暦0点なら reject', judgeAll([full, cutOff]).verdict, 'reject')
check('合計は平均で見る', judgeAll([full, { q1_line: 3, q2_kurashi: 3, q3_koyomi: 3, q4_taigi: 3 }]).avgTotal, 16)
check('adopt は層二から', tierForVerdict('adopt'), 'tier2')
check('trial は層一から', tierForVerdict('trial'), 'tier1')
check('hold は起用しない', tierForVerdict('hold'), null)

// --- JST と候の切り替わり ---------------------------------------
// UTC 15:00 は JST では翌日 0:00。UTC のまま日付を見ると1日ずれる
const boundary = new Date('2026-09-07T15:00:00Z')
check('JST の日付境界（UTC 9/7 15:00 → JST 9/8）', jstYmd(boundary), '2026-09-08')
check('JST の MM-DD', jstMonthDay(boundary), '09-08')

const koList = [
  { id: 1, slug: 'harukaze-kori-o-toku', starts_md: '02-04' },
  { id: 43, slug: 'kusa-no-tsuyu-shiroshi', starts_md: '09-08' },
  { id: 42, slug: 'kokumono-sunawachi-minoru', starts_md: '09-02' },
  { id: 66, slug: 'yuki-watarite-mugi-nobiru', starts_md: '12-31' },
  { id: 72, slug: 'niwatori-hajimete-toya-ni-tsuku', starts_md: '01-30' },
  { id: 70, slug: 'fuki-no-hana-saku', starts_md: '01-20' },
]

check('候の切り替わり当日は新しい候', pickKoForDate(koList, boundary)?.slug, 'kusa-no-tsuyu-shiroshi')
check(
  '切り替わり前日（JST 9/7）は前の候',
  pickKoForDate(koList, new Date('2026-09-07T14:59:00Z'))?.slug,
  'kokumono-sunawachi-minoru',
)
check('立春前の2月頭は前年最後の候', pickKoForDate(koList, new Date('2026-02-01T03:00:00Z'))?.slug, 'niwatori-hajimete-toya-ni-tsuku')
check('1月下旬は大寒の候', pickKoForDate(koList, new Date('2026-01-22T03:00:00Z'))?.slug, 'fuki-no-hana-saku')
check('1/1〜1/4 は前年12/31の候に落とす', pickKoForDate(koList, new Date('2026-01-02T03:00:00Z'))?.slug, 'yuki-watarite-mugi-nobiru')

console.log(failed === 0 ? '\nすべて通りました' : `\n${failed}件 失敗`)
process.exit(failed === 0 ? 0 : 1)
