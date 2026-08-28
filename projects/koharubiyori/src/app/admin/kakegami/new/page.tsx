import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAdminUser } from '@/lib/auth'
import { listCreatorOptions, listKo } from '@/lib/koharu/queries'
import { STATUS_LABELS } from '@/lib/koharu/constants'
import { jstYmd, pickKoForDate } from '@/lib/koharu/date'
import { createKakegamiAction } from '../actions'

export const metadata = { title: '掛け紙の発行登録' }

export default async function NewKakegamiPage() {
  const user = await getAdminUser()
  if (!user) redirect('/admin/login')

  const [koList, creators] = await Promise.all([listKo(), listCreatorOptions()])
  const todayKo = pickKoForDate(koList)

  return (
    <main className="mx-auto w-full max-w-[720px] px-5 py-10 sm:px-6">
      <nav className="text-[12px] text-sumi-55">
        <Link href="/admin/kakegami" className="hover:text-hare">
          掛け紙
        </Link>
        <span className="px-1.5">／</span>
        <span>発行登録</span>
      </nav>

      <h1 className="mt-6 text-[24px]">掛け紙の発行を登録する</h1>
      <p className="mt-2 text-[13px] text-sumi-55">
        登録すると裏面QRのURLが確定します。刷る前に本番ドメインを確定してください。
      </p>

      {koList.length === 0 ? (
        <p className="mt-8 border border-hare/40 bg-hare/8 px-4 py-3 text-[13px] text-hare">
          七十二候マスタが空です。supabase/seed/0004_koyomi_ko_seed.sql を先に流してください。
        </p>
      ) : null}

      <form action={createKakegamiAction} className="mt-8 space-y-6">
        <div>
          <label htmlFor="ko_id" className="block text-[13px] text-sumi-70">
            候 <span className="text-hare">*</span>
          </label>
          <select
            id="ko_id"
            name="ko_id"
            required
            defaultValue={todayKo ? String(todayKo.id) : ''}
            className="mt-1.5 w-full border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
          >
            <option value="">選んでください</option>
            {koList.map((ko) => (
              <option key={ko.id} value={ko.id}>
                {ko.starts_md.replace('-', '/')}　{ko.name}（{ko.reading}）
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="creator_id" className="block text-[13px] text-sumi-70">
            描き手
          </label>
          <select
            id="creator_id"
            name="creator_id"
            defaultValue=""
            className="mt-1.5 w-full border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
          >
            <option value="">未定</option>
            {creators.map((creator) => (
              <option key={creator.id} value={creator.id}>
                {creator.name}
              </option>
            ))}
          </select>
        </div>

        <div className="grid gap-6 sm:grid-cols-2">
          <div>
            <label htmlFor="issue_date" className="block text-[13px] text-sumi-70">
              発行日（JST） <span className="text-hare">*</span>
            </label>
            <input
              id="issue_date"
              name="issue_date"
              type="date"
              required
              defaultValue={jstYmd()}
              className="mt-1.5 w-full border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
            />
          </div>
          <div>
            <label htmlFor="print_qty" className="block text-[13px] text-sumi-70">
              刷り部数
            </label>
            <input
              id="print_qty"
              name="print_qty"
              type="number"
              min={0}
              className="mt-1.5 w-full border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
            />
          </div>
          <div>
            <label htmlFor="distributed_qty" className="block text-[13px] text-sumi-70">
              配布実績
            </label>
            <p className="mt-0.5 text-[12px] text-sumi-55">スキャン率の分母。あとから入れてよい</p>
            <input
              id="distributed_qty"
              name="distributed_qty"
              type="number"
              min={0}
              className="mt-1.5 w-full border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
            />
          </div>
          <div>
            <label htmlFor="status" className="block text-[13px] text-sumi-70">
              公開状態
            </label>
            <select
              id="status"
              name="status"
              defaultValue="draft"
              className="mt-1.5 w-full border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
            >
              {(['draft', 'published', 'archived'] as const).map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label htmlFor="artwork_url" className="block text-[13px] text-sumi-70">
            掛け紙の絵のURL
          </label>
          <input
            id="artwork_url"
            name="artwork_url"
            className="mt-1.5 w-full border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
          />
        </div>

        <div>
          <label htmlFor="notes" className="block text-[13px] text-sumi-70">
            メモ
          </label>
          <textarea
            id="notes"
            name="notes"
            rows={3}
            className="mt-1.5 w-full border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
          />
        </div>

        <button
          type="submit"
          className="bg-sumi px-6 py-3 text-[14px] text-washi transition-opacity hover:opacity-85"
        >
          登録する
        </button>
      </form>
    </main>
  )
}
