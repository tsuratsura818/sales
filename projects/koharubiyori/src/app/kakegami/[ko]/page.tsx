import type { Metadata } from 'next'
import Image from 'next/image'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { JsonLd, breadcrumbJsonLd } from '@/components/koharu/json-ld'
import { BRAND_NAME } from '@/lib/koharu/constants'
import { formatJaDate } from '@/lib/koharu/date'
import { getKoBySlug, listPublishedKakegamiByKo } from '@/lib/koharu/queries'
import { absoluteUrl } from '@/lib/site'

type Props = { params: Promise<{ ko: string }> }

export const revalidate = 300

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { ko: koSlug } = await params
  const ko = await getKoBySlug(koSlug)
  if (!ko) return { title: '見つかりませんでした' }

  const description = ko.copy ?? `${ko.name}（${ko.reading}）の掛け紙。`

  return {
    title: `${ko.name}の掛け紙`,
    description,
    alternates: { canonical: absoluteUrl(`/kakegami/${ko.slug}`) },
    openGraph: {
      title: `${ko.name}の掛け紙｜${BRAND_NAME}`,
      description,
      url: absoluteUrl(`/kakegami/${ko.slug}`),
    },
  }
}

export default async function KakegamiPage({ params }: Props) {
  const { ko: koSlug } = await params

  // スラッグはマスタの slug 列が唯一の正。コードでローマ字を組み立てない
  const ko = await getKoBySlug(koSlug)
  if (!ko) notFound()

  const sheets = await listPublishedKakegamiByKo(ko.id)

  return (
    <main className="mx-auto w-full max-w-[720px] px-5 pb-24 pt-6 sm:px-6">
      <JsonLd
        data={breadcrumbJsonLd([
          { name: BRAND_NAME, url: absoluteUrl('/') },
          { name: '掛け紙', url: absoluteUrl('/kakegami') },
          { name: ko.name, url: absoluteUrl(`/kakegami/${ko.slug}`) },
        ])}
      />

      <nav className="text-[12px] text-sumi-55">
        <Link href="/" className="hover:text-hare">
          {BRAND_NAME}
        </Link>
        <span className="px-1.5">／</span>
        <span>{ko.name}</span>
      </nav>

      <header className="mt-8">
        {ko.sekki ? <p className="text-[13px] tracking-widest text-hare">{ko.sekki}</p> : null}
        <h1 className="mt-2 text-[32px] leading-tight sm:text-[38px]">{ko.name}</h1>
        <p className="mt-2 text-[13px] text-sumi-55">{ko.reading}</p>
        <p className="tabular mt-1 text-[13px] text-sumi-55">
          {ko.starts_md.replace('-', '月')}日ごろから
        </p>
      </header>

      {ko.copy ? (
        <p className="mt-8 whitespace-pre-line text-[16px] leading-[1.95]">{ko.copy}</p>
      ) : null}

      {sheets.length === 0 ? (
        <p className="mt-12 text-[14px] text-sumi-55">この候の掛け紙は、まだ公開されていません。</p>
      ) : (
        <section className="mt-12 space-y-14">
          {sheets.map((sheet) => (
            <div key={sheet.id}>
              {sheet.artwork_url ? (
                <div className="overflow-hidden bg-washi-shade">
                  <Image
                    src={sheet.artwork_url}
                    alt={`${ko.name}の掛け紙`}
                    width={1080}
                    height={1350}
                    sizes="(min-width: 768px) 720px, 100vw"
                    priority
                    className="h-auto w-full object-cover"
                  />
                </div>
              ) : null}

              <dl className="mt-5 border-t border-line text-[14px]">
                <div className="flex gap-4 border-b border-line py-3">
                  <dt className="w-24 shrink-0 text-sumi-55">描き手</dt>
                  <dd>
                    {sheet.creator && sheet.creator.status === 'published' ? (
                      <Link href={`/sakka/${sheet.creator.slug}`} className="text-hare underline-offset-4 hover:underline">
                        {sheet.creator.name}
                      </Link>
                    ) : (
                      (sheet.creator?.name ?? '—')
                    )}
                  </dd>
                </div>
                {sheet.character ? (
                  <div className="flex gap-4 border-b border-line py-3">
                    <dt className="w-24 shrink-0 text-sumi-55">この絵の主</dt>
                    <dd>{sheet.character.name}</dd>
                  </div>
                ) : null}
                <div className="flex gap-4 border-b border-line py-3">
                  <dt className="w-24 shrink-0 text-sumi-55">発行</dt>
                  <dd className="tabular">{formatJaDate(sheet.issue_date)}</dd>
                </div>
              </dl>
            </div>
          ))}
        </section>
      )}
    </main>
  )
}
