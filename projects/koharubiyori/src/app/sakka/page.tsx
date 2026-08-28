import type { Metadata } from 'next'
import Link from 'next/link'
import Image from 'next/image'
import { JsonLd, breadcrumbJsonLd } from '@/components/koharu/json-ld'
import { BRAND_NAME } from '@/lib/koharu/constants'
import { listPublishedCreators } from '@/lib/koharu/queries'
import { absoluteUrl } from '@/lib/site'

export const revalidate = 300

export const metadata: Metadata = {
  title: '作家',
  description: `${BRAND_NAME}の掛け紙を描く作家たち。`,
  alternates: { canonical: absoluteUrl('/sakka') },
}

export default async function SakkaIndexPage() {
  const creators = await listPublishedCreators()

  return (
    <main className="mx-auto w-full max-w-[720px] px-5 pb-24 pt-6 sm:px-6">
      <JsonLd
        data={breadcrumbJsonLd([
          { name: BRAND_NAME, url: absoluteUrl('/') },
          { name: '作家', url: absoluteUrl('/sakka') },
        ])}
      />

      <nav className="text-[12px] text-sumi-55">
        <Link href="/" className="hover:text-hare">
          {BRAND_NAME}
        </Link>
        <span className="px-1.5">／</span>
        <span>作家</span>
      </nav>

      <h1 className="mt-8 text-[30px] leading-tight">掛け紙を描いた作家</h1>

      {creators.length === 0 ? (
        <p className="mt-8 text-[14px] text-sumi-55">公開中の作家はまだいません。</p>
      ) : (
        <ul className="mt-8 grid grid-cols-2 gap-x-4 gap-y-8 sm:grid-cols-3">
          {creators.map((creator) => {
            const image = creator.hero_image_url ?? creator.photo_url
            return (
            <li key={creator.id}>
              <Link href={`/sakka/${creator.slug}`} className="block hover:opacity-80">
                <div className="aspect-4/5 w-full overflow-hidden bg-washi-shade">
                  {image ? (
                    <Image
                      src={image}
                      alt={creator.name}
                      width={480}
                      height={600}
                      sizes="(min-width: 768px) 240px, 45vw"
                      className="h-full w-full object-cover"
                    />
                  ) : null}
                </div>
                <p className="mt-3 font-mincho text-[17px] leading-snug">{creator.name}</p>
                {creator.title ? (
                  <p className="mt-0.5 text-[12px] text-sumi-55">{creator.title}</p>
                ) : null}
              </Link>
            </li>
            )
          })}
        </ul>
      )}
    </main>
  )
}
