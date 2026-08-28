import type { Metadata } from 'next'
import Link from 'next/link'
import { JsonLd, breadcrumbJsonLd } from '@/components/koharu/json-ld'
import { BRAND_NAME } from '@/lib/koharu/constants'
import { pickKoForDate } from '@/lib/koharu/date'
import { listKo } from '@/lib/koharu/queries'
import { absoluteUrl } from '@/lib/site'

export const revalidate = 3600

export const metadata: Metadata = {
  title: '掛け紙',
  description: `七十二候にあわせて描き下ろす、${BRAND_NAME}の掛け紙。`,
  alternates: { canonical: absoluteUrl('/kakegami') },
}

export default async function KakegamiIndexPage() {
  const koList = await listKo()
  const todayKo = pickKoForDate(koList)

  return (
    <main className="mx-auto w-full max-w-[720px] px-5 pb-24 pt-6 sm:px-6">
      <JsonLd
        data={breadcrumbJsonLd([
          { name: BRAND_NAME, url: absoluteUrl('/') },
          { name: '掛け紙', url: absoluteUrl('/kakegami') },
        ])}
      />

      <nav className="text-[12px] text-sumi-55">
        <Link href="/" className="hover:text-hare">
          {BRAND_NAME}
        </Link>
        <span className="px-1.5">／</span>
        <span>掛け紙</span>
      </nav>

      <h1 className="mt-8 text-[30px] leading-tight">七十二候の掛け紙</h1>

      <ul className="mt-8 border-t border-line">
        {koList.map((ko) => (
          <li key={ko.id} className="border-b border-line">
            <Link
              href={`/kakegami/${ko.slug}`}
              className="flex items-baseline gap-3 py-3 hover:text-hare"
              aria-current={todayKo?.id === ko.id ? 'true' : undefined}
            >
              <span className="tabular w-16 shrink-0 text-[12px] text-sumi-55">
                {ko.starts_md.replace('-', '/')}
              </span>
              <span className="font-mincho text-[16px]">{ko.name}</span>
              <span className="text-[12px] text-sumi-55">{ko.reading}</span>
              {todayKo?.id === ko.id ? (
                <span className="ml-auto text-[11px] text-hare">いまの候</span>
              ) : null}
            </Link>
          </li>
        ))}
      </ul>
    </main>
  )
}
