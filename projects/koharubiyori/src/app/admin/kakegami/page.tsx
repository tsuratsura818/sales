import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAdminUser } from '@/lib/auth'
import { listKakegamiForAdmin } from '@/lib/koharu/queries'
import { SCAN_RATE_TARGET_PCT, STATUS_LABELS } from '@/lib/koharu/constants'
import { formatJaDate } from '@/lib/koharu/date'
import { qrUrl } from '@/lib/site'
import { updateDistributedAction } from './actions'

export const metadata = { title: '掛け紙の発行管理' }

export default async function AdminKakegamiPage() {
  const user = await getAdminUser()
  if (!user) redirect('/admin/login')

  const rows = await listKakegamiForAdmin()

  return (
    <main className="mx-auto w-full max-w-[1080px] px-5 py-10 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[24px]">掛け紙</h1>
        <Link
          href="/admin/kakegami/new"
          className="bg-sumi px-4 py-2.5 text-[14px] text-washi hover:opacity-85"
        >
          発行を登録
        </Link>
      </div>
      <p className="mt-2 text-[12px] text-sumi-55">
        スキャン率 = スキャン数 ÷ 配布実績。目標は {SCAN_RATE_TARGET_PCT}%。層二→層三の昇格判断に使う。
      </p>

      {rows.length === 0 ? (
        <p className="mt-10 text-[14px] text-sumi-55">まだ掛け紙が登録されていません。</p>
      ) : (
        <div className="mt-6 overflow-x-auto">
          <table className="w-full min-w-[940px] border-collapse text-[14px]">
            <thead>
              <tr className="border-y border-line text-left text-[12px] text-sumi-55">
                <th className="py-2.5 pr-4 font-normal">候</th>
                <th className="py-2.5 pr-4 font-normal">描き手</th>
                <th className="py-2.5 pr-4 font-normal">発行日</th>
                <th className="py-2.5 pr-4 text-right font-normal">刷り</th>
                <th className="py-2.5 pr-4 text-right font-normal">スキャン</th>
                <th className="py-2.5 pr-4 text-right font-normal">スキャン率</th>
                <th className="py-2.5 pr-4 font-normal">配布実績・公開</th>
                <th className="py-2.5 font-normal">QR</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const rate = row.scanRatePct
                const isBelowTarget = rate !== null && rate < SCAN_RATE_TARGET_PCT
                return (
                  <tr key={row.kakegami.id} className="border-b border-line align-top">
                    <td className="py-3 pr-4">
                      {row.ko ? (
                        <>
                          <span className="font-mincho">{row.ko.name}</span>
                          <span className="block text-[11px] text-sumi-55">{row.ko.reading}</span>
                        </>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="py-3 pr-4 text-[13px]">
                      {row.creator ? (
                        <Link
                          href={`/admin/creators/${row.creator.id}`}
                          className="hover:text-hare"
                        >
                          {row.creator.name}
                        </Link>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="tabular py-3 pr-4 text-[13px]">
                      {formatJaDate(row.kakegami.issue_date)}
                    </td>
                    <td className="tabular py-3 pr-4 text-right">
                      {row.kakegami.print_qty ?? '—'}
                    </td>
                    <td className="tabular py-3 pr-4 text-right">{row.scanCount}</td>
                    <td
                      className={`tabular py-3 pr-4 text-right ${isBelowTarget ? 'text-hare' : ''}`}
                    >
                      {rate === null ? '—' : `${rate}%`}
                    </td>
                    <td className="py-3 pr-4">
                      <form action={updateDistributedAction} className="flex flex-wrap gap-2">
                        <input type="hidden" name="id" value={row.kakegami.id} />
                        <input
                          name="distributed_qty"
                          type="number"
                          min={0}
                          defaultValue={row.kakegami.distributed_qty ?? ''}
                          aria-label="配布実績"
                          className="tabular w-24 border border-line px-2 py-1.5 text-[13px] outline-none focus:border-hare"
                        />
                        <select
                          name="status"
                          defaultValue={row.kakegami.status}
                          aria-label="公開状態"
                          className="border border-line bg-white px-2 py-1.5 text-[13px] outline-none focus:border-hare"
                        >
                          {(['draft', 'published', 'archived'] as const).map((s) => (
                            <option key={s} value={s}>
                              {STATUS_LABELS[s]}
                            </option>
                          ))}
                        </select>
                        <button
                          type="submit"
                          className="border border-sumi px-3 py-1.5 text-[13px] hover:bg-washi-shade"
                        >
                          保存
                        </button>
                      </form>
                    </td>
                    <td className="py-3">
                      <code className="text-[11px] break-all text-sumi-55">
                        {qrUrl(row.kakegami.id)}
                      </code>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </main>
  )
}
