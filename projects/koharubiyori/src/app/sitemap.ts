import type { MetadataRoute } from 'next'
import { listKo, listPublishedCreatorSlugs } from '@/lib/koharu/queries'
import { absoluteUrl } from '@/lib/site'

export const revalidate = 3600

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [creatorSlugs, koList] = await Promise.all([listPublishedCreatorSlugs(), listKo()])

  return [
    { url: absoluteUrl('/'), priority: 1 },
    { url: absoluteUrl('/sakka'), priority: 0.7 },
    { url: absoluteUrl('/kakegami'), priority: 0.7 },
    ...creatorSlugs.map((slug) => ({ url: absoluteUrl(`/sakka/${slug}`), priority: 0.8 })),
    ...koList.map((ko) => ({ url: absoluteUrl(`/kakegami/${ko.slug}`), priority: 0.6 })),
  ]
}
