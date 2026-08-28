import Link from 'next/link'
import { BRAND_DEFINITION, BRAND_NAME, BRAND_NAME_KANA } from '@/lib/koharu/constants'
import { pickKoForDate } from '@/lib/koharu/date'
import { listKo, listPublishedCreatorSlugs } from '@/lib/koharu/queries'

export const revalidate = 3600

export default async function HomePage() {
  const [koList, creatorSlugs] = await Promise.all([listKo(), listPublishedCreatorSlugs()])
  const todayKo = pickKoForDate(koList)

  return (
    <main className="mx-auto w-full max-w-[720px] px-5 pb-24 pt-16 sm:px-6">
      <h1 className="text-[34px] leading-tight sm:text-[42px]">{BRAND_NAME}</h1>
      <p className="mt-2 text-[13px] tracking-widest text-sumi-55">{BRAND_NAME_KANA}</p>

      {/* 定義構文は表記を揺らさない（AEO） */}
      <p className="mt-8 text-[16px] leading-[1.95]">{BRAND_DEFINITION}</p>

      {todayKo ? (
        <section className="mt-14 border-t border-line pt-8">
          <p className="text-[12px] tracking-widest text-hare">いまの候</p>
          <h2 className="mt-2 text-[26px]">{todayKo.name}</h2>
          <p className="mt-1 text-[13px] text-sumi-55">{todayKo.reading}</p>
          {todayKo.copy ? (
            <p className="mt-4 text-[15px] leading-[1.95]">{todayKo.copy}</p>
          ) : null}
          <Link
            href={`/kakegami/${todayKo.slug}`}
            className="mt-5 inline-block text-[14px] text-hare underline-offset-4 hover:underline"
          >
            この候の掛け紙を見る →
          </Link>
        </section>
      ) : null}

      {creatorSlugs.length > 0 ? (
        <section className="mt-12 border-t border-line pt-8">
          <Link href="/sakka" className="text-[14px] text-hare underline-offset-4 hover:underline">
            掛け紙を描いた作家たち →
          </Link>
        </section>
      ) : null}
    </main>
  )
}
