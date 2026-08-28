type JsonLdValue = string | number | boolean | null | JsonLdObject | JsonLdValue[]
type JsonLdObject = { [key: string]: JsonLdValue | undefined }

export function JsonLd({ data }: { data: JsonLdObject }) {
  return (
    <script
      type="application/ld+json"
      // JSON.stringify した値のみを入れる。ユーザー入力はここで </script> を割らないようエスケープする
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(data).replace(/</g, '\\u003c'),
      }}
    />
  )
}

/** 全ページに入れる。項目は「表示順」に渡す */
export function breadcrumbJsonLd(items: { name: string; url: string }[]): JsonLdObject {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((item, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: item.name,
      item: item.url,
    })),
  }
}
