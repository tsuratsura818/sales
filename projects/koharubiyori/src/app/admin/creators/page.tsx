import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAdminUser } from '@/lib/auth'
import { listCreatorsForAdmin } from '@/lib/koharu/queries'
import { STATUS_LABELS, TIER_SHORT_LABELS, VERDICT_LABELS } from '@/lib/koharu/constants'
import { formatJaDate } from '@/lib/koharu/date'

export const metadata = { title: '作家一覧' }

export default async function AdminCreatorsPage() {
  const user = await getAdminUser()
  if (!user) redirect('/admin/login')

  // 合計点の降順で返る（未採点は末尾）
  const rows = await listCreatorsForAdmin()

  return (
    <main className="mx-auto w-full max-w-[1080px] px-5 py-10 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[24px]">作家</h1>
        <Link href="/admin/creators/new" className="bg-sumi px-4 py-2.5 text-[14px] text-washi hover:opacity-85">
          新規登録
        </Link>
      </div>
      <p className="mt-2 text-[12px] text-sumi-55">
        合計点の高い順。点は作家が持つキャラクターのうち最も高い平均点。
      </p>

      {rows.length === 0 ? (
        <p className="mt-10 text-[14px] text-sumi-55">まだ作家が登録されていません。</p>
      ) : (
        <div className="mt-6 overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-[14px]">
            <thead>
              <tr className="border-y border-line text-left text-[12px] text-sumi-55">
                <th className="py-2.5 pr-4 font-normal">名前</th>
                <th className="py-2.5 pr-4 font-normal">層</th>
                <th className="py-2.5 pr-4 text-right font-normal">合計点</th>
                <th className="py-2.5 pr-4 font-normal">判定</th>
                <th className="py-2.5 pr-4 text-right font-normal">採点者</th>
                <th className="py-2.5 pr-4 text-right font-normal">掛け紙</th>
                <th className="py-2.5 pr-4 font-normal">最終起用日</th>
                <th className="py-2.5 font-normal">公開</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.creator.id} className="border-b border-line">
                  <td className="py-3 pr-4">
                    <Link href={`/admin/creators/${row.creator.id}`} className="hover:text-hare">
                      {row.creator.name}
                    </Link>
                    {row.creator.name_kana ? (
                      <span className="block text-[11px] text-sumi-55">{row.creator.name_kana}</span>
                    ) : null}
                  </td>
                  <td className="py-3 pr-4 text-[13px]">
                    {row.creator.current_tier ? TIER_SHORT_LABELS[row.creator.current_tier] : '—'}
                  </td>
                  <td className="tabular py-3 pr-4 text-right">
                    {row.bestAvgTotal === null ? '—' : row.bestAvgTotal}
                  </td>
                  <td className="py-3 pr-4 text-[13px]">
                    {row.bestVerdict ? VERDICT_LABELS[row.bestVerdict] : '—'}
                    {row.bestVerdict && !row.isConfirmable ? (
                      <span className="block text-[11px] text-hare">採点者1名・未確定</span>
                    ) : null}
                  </td>
                  <td className="tabular py-3 pr-4 text-right">{row.bestScorerCount}</td>
                  <td className="tabular py-3 pr-4 text-right">{row.kakegamiCount}</td>
                  <td className="tabular py-3 pr-4 text-[13px]">
                    {formatJaDate(row.lastEngagedOn)}
                  </td>
                  <td className="py-3 text-[13px]">{STATUS_LABELS[row.creator.status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  )
}
