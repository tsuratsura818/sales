import Image from 'next/image'
import { HareMaBadge } from './hare-ma-badge'
import { KakegamiCard } from './kakegami-card'
import type { Character, Creator, CreatorKakegami } from '@/lib/koharu/queries'
import type { Enums } from '@/types/database'
import { HARE_MA_ORDER } from '@/lib/koharu/constants'

type ExternalLink = { label: string; href: string }

function externalLinksOf(creator: Creator): ExternalLink[] {
  return [
    { label: '作家のオンラインストア', href: creator.ec_url },
    { label: 'Instagram', href: creator.sns_instagram },
    { label: 'X', href: creator.sns_x },
    { label: 'ウェブサイト', href: creator.website_url },
  ].filter((link): link is ExternalLink => Boolean(link.href))
}

/** 担当した晴れ間を、六つの並び順で重複なく出す */
function hareMaOf(characters: Character[]): Enums<'hare_ma'>[] {
  const owned = new Set(characters.map((c) => c.hare_ma).filter((h): h is Enums<'hare_ma'> => !!h))
  return HARE_MA_ORDER.filter((h) => owned.has(h))
}

export function CreatorProfile({
  creator,
  characters,
  kakegami,
}: {
  creator: Creator
  characters: Character[]
  kakegami: CreatorKakegami[]
}) {
  const links = externalLinksOf(creator)
  const hareMa = hareMaOf(characters)

  return (
    <article className="mx-auto w-full max-w-[720px] px-5 pb-24 pt-10 sm:px-6">
      <header>
        <h1 className="text-[30px] leading-tight sm:text-[36px]">{creator.name}</h1>
        {creator.name_kana ? (
          <p className="mt-1.5 text-[13px] text-sumi-55">{creator.name_kana}</p>
        ) : null}
        <p className="mt-3 text-[14px] text-sumi-70">
          {[creator.title, creator.base_area].filter(Boolean).join('／')}
        </p>
      </header>

      {/* 作家ページに限り、絵がページの中で最も大きい要素になる（CLAUDE.md §5） */}
      {creator.hero_image_url ? (
        <div className="mt-8 overflow-hidden bg-washi-shade">
          <Image
            src={creator.hero_image_url}
            alt={`${creator.name}の作品`}
            width={1440}
            height={1080}
            sizes="(min-width: 768px) 720px, 100vw"
            priority
            className="h-auto w-full object-cover"
          />
        </div>
      ) : null}

      {hareMa.length > 0 ? (
        <div className="mt-6 flex flex-wrap gap-2">
          {hareMa.map((h) => (
            <HareMaBadge key={h} hareMa={h} />
          ))}
        </div>
      ) : null}

      {creator.profile ? (
        <section className="mt-8">
          <p className="whitespace-pre-line text-[15px] leading-[1.9]">{creator.profile}</p>
        </section>
      ) : null}

      {creator.tsukumo_note ? (
        <aside className="mt-8 border-l-2 border-hare/50 bg-washi-shade/60 py-4 pl-4 pr-4">
          <p className="text-[12px] tracking-wider text-hare">編集長ツクモの一言</p>
          <p className="mt-1.5 text-[14px] leading-[1.85]">{creator.tsukumo_note}</p>
        </aside>
      ) : null}

      {kakegami.length > 0 ? (
        <section className="mt-12">
          <h2 className="text-[20px]">この作家が描いた掛け紙</h2>
          <div className="mt-5 grid grid-cols-2 gap-x-4 gap-y-8 sm:grid-cols-3">
            {kakegami.map((item) => (
              <KakegamiCard key={item.id} item={item} />
            ))}
          </div>
        </section>
      ) : null}

      {links.length > 0 ? (
        <section className="mt-12">
          <h2 className="text-[20px]">この作家をたずねる</h2>
          <ul className="mt-4 border-t border-line">
            {links.map((link) => (
              <li key={link.href} className="border-b border-line">
                <a
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-between gap-4 py-3.5 text-[15px] transition-colors hover:text-hare"
                >
                  <span>{link.label}</span>
                  <span aria-hidden className="text-[12px] text-sumi-55">
                    別のサイトへ ↗
                  </span>
                  <span className="sr-only">（外部サイトを新しいタブで開きます）</span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  )
}
