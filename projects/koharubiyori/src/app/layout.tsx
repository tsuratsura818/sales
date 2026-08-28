import type { Metadata } from 'next'
import { BRAND_DEFINITION, BRAND_NAME } from '@/lib/koharu/constants'
import { JsonLd } from '@/components/koharu/json-ld'
import { SITE_URL, absoluteUrl } from '@/lib/site'
import './globals.css'

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: `${BRAND_NAME}｜京都・河原町の露店限定の編集レーベル`,
    template: `%s｜${BRAND_NAME}`,
  },
  description: BRAND_DEFINITION,
  openGraph: {
    siteName: BRAND_NAME,
    locale: 'ja_JP',
    type: 'website',
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body className="min-h-dvh bg-washi text-sumi antialiased">
        <JsonLd
          data={{
            '@context': 'https://schema.org',
            '@type': 'Organization',
            '@id': absoluteUrl('/#organization'),
            name: BRAND_NAME,
            alternateName: 'こはるびより',
            description: BRAND_DEFINITION,
            url: SITE_URL,
            areaServed: { '@type': 'Place', name: '京都府京都市 河原町' },
          }}
        />
        {children}
      </body>
    </html>
  )
}
