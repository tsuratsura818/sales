import Image from 'next/image'
import Link from 'next/link'
import { formatJaDate } from '@/lib/koharu/date'
import type { CreatorKakegami } from '@/lib/koharu/queries'

/** 作家ページの「この作家が描いた掛け紙」1枚ぶん */
export function KakegamiCard({ item }: { item: CreatorKakegami }) {
  const ko = item.ko

  const body = (
    <>
      <div className="relative aspect-4/5 w-full overflow-hidden bg-washi-shade">
        {item.artwork_url ? (
          <Image
            src={item.artwork_url}
            alt={ko ? `${ko.name}の掛け紙` : '掛け紙'}
            width={480}
            height={600}
            sizes="(min-width: 768px) 240px, 45vw"
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-[13px] text-sumi-55">
            画像未登録
          </div>
        )}
      </div>
      <div className="pt-3">
        <p className="font-mincho text-[17px] leading-snug">{ko?.name ?? '—'}</p>
        <p className="mt-0.5 text-[12px] text-sumi-55">{ko?.reading ?? ''}</p>
        <p className="tabular mt-1 text-[12px] text-sumi-55">{formatJaDate(item.issue_date)}</p>
      </div>
    </>
  )

  if (!ko) return <div className="block">{body}</div>

  return (
    <Link
      href={`/kakegami/${ko.slug}`}
      className="block transition-opacity hover:opacity-80 focus-visible:opacity-80"
    >
      {body}
    </Link>
  )
}
