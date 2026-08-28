import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import { CreatorProfile } from '@/components/koharu/creator-profile'
import { JsonLd, breadcrumbJsonLd } from '@/components/koharu/json-ld'
import { BRAND_NAME } from '@/lib/koharu/constants'
import {
  getPublishedCreatorBySlug,
  listPublishedCharactersByCreator,
  listPublishedKakegamiByCreator,
} from '@/lib/koharu/queries'
import { absoluteUrl } from '@/lib/site'

type Props = { params: Promise<{ slug: string }> }

export const revalidate = 300

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params
  const creator = await getPublishedCreatorBySlug(slug)
  if (!creator) return { title: '見つかりませんでした' }

  const title = `${creator.name}`
  const description =
    creator.profile?.slice(0, 110) ??
    `${creator.name}は${BRAND_NAME}の掛け紙を描く作家です。`
  const image = creator.hero_image_url ?? creator.photo_url ?? undefined

  return {
    title,
    description,
    alternates: { canonical: absoluteUrl(`/sakka/${creator.slug}`) },
    openGraph: {
      title: `${title}｜${BRAND_NAME}`,
      description,
      url: absoluteUrl(`/sakka/${creator.slug}`),
      type: 'profile',
      images: image ? [{ url: image }] : undefined,
    },
  }
}

export default async function SakkaPage({ params }: Props) {
  const { slug } = await params

  // published 以外は 404。下書きの作家ページを URL 直打ちで見せない
  const creator = await getPublishedCreatorBySlug(slug)
  if (!creator) notFound()

  const [characters, kakegami] = await Promise.all([
    listPublishedCharactersByCreator(creator.id),
    listPublishedKakegamiByCreator(creator.id),
  ])

  const url = absoluteUrl(`/sakka/${creator.slug}`)
  const sameAs = [creator.sns_x, creator.sns_instagram, creator.website_url, creator.ec_url].filter(
    (v): v is string => Boolean(v),
  )

  return (
    <main>
      <JsonLd
        data={{
          '@context': 'https://schema.org',
          '@type': 'Person',
          '@id': `${url}#person`,
          name: creator.name,
          alternateName: creator.name_kana ?? undefined,
          jobTitle: creator.title ?? undefined,
          description: creator.profile ?? undefined,
          image: creator.hero_image_url ?? creator.photo_url ?? undefined,
          url,
          sameAs: sameAs.length > 0 ? sameAs : undefined,
          affiliation: { '@type': 'Organization', '@id': absoluteUrl('/#organization') },
        }}
      />
      <JsonLd
        data={breadcrumbJsonLd([
          { name: BRAND_NAME, url: absoluteUrl('/') },
          { name: '作家', url: absoluteUrl('/sakka') },
          { name: creator.name, url },
        ])}
      />

      <nav className="mx-auto w-full max-w-[720px] px-5 pt-6 text-[12px] text-sumi-55 sm:px-6">
        <Link href="/" className="hover:text-hare">
          {BRAND_NAME}
        </Link>
        <span className="px-1.5">／</span>
        <span>{creator.name}</span>
      </nav>

      <CreatorProfile creator={creator} characters={characters} kakegami={kakegami} />
    </main>
  )
}
