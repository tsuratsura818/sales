import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAdminUser } from '@/lib/auth'
import { listCreatorsForAdmin, listKakegamiForAdmin } from '@/lib/koharu/queries'
import { SCAN_RATE_TARGET_PCT } from '@/lib/koharu/constants'

export default async function AdminHomePage() {
  const user = await getAdminUser()
  if (!user) redirect('/admin/login')

  const [creators, kakegami] = await Promise.all([listCreatorsForAdmin(), listKakegamiForAdmin()])

  const scored = creators.filter((row) => row.bestAvgTotal !== null).length
  const adopted = creators.filter((row) => row.bestVerdict === 'adopt' && row.isConfirmable).length
  const withRate = kakegami.filter((row) => row.scanRatePct !== null)
  const avgRate =
    withRate.length > 0
      ? Math.round(
          (withRate.reduce((sum, row) => sum + (row.scanRatePct ?? 0), 0) / withRate.length) * 10,
        ) / 10
      : null

  const cards = [
    { label: '登録作家', value: `${creators.length}名` },
    { label: '採点済み', value: `${scored}名` },
    { label: '採用（2名採点済み）', value: `${adopted}名` },
    {
      label: `平均スキャン率（目標 ${SCAN_RATE_TARGET_PCT}%）`,
      value: avgRate === null ? '—' : `${avgRate}%`,
    },
  ]

  return (
    <main className="mx-auto w-full max-w-[1080px] px-5 py-10 sm:px-6">
      <h1 className="text-[24px]">ダッシュボード</h1>
      <p className="mt-1 text-[12px] text-sumi-55">{user.email}</p>

      <div className="mt-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {cards.map((card) => (
          <div key={card.label} className="border border-line bg-white px-4 py-4">
            <p className="text-[12px] leading-snug text-sumi-55">{card.label}</p>
            <p className="tabular mt-2 font-mincho text-[26px]">{card.value}</p>
          </div>
        ))}
      </div>

      <div className="mt-10 flex flex-wrap gap-4 text-[14px]">
        <Link href="/admin/creators/new" className="bg-sumi px-4 py-2.5 text-washi hover:opacity-85">
          作家を登録する
        </Link>
        <Link
          href="/admin/kakegami/new"
          className="border border-sumi px-4 py-2.5 hover:bg-washi-shade"
        >
          掛け紙を登録する
        </Link>
      </div>
    </main>
  )
}
