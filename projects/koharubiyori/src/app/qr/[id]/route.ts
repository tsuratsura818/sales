import { NextResponse, type NextRequest } from 'next/server'
import { getKakegamiForScan, recordKakegamiScan } from '@/lib/koharu/queries'
import { absoluteUrl } from '@/lib/site'

/**
 * 掛け紙裏QRの着地点。スキャンを1件記録して候の掛け紙ページへ送る。
 *
 * ★ このURLスキーム（/qr/[kakegami_id]）は掛け紙に刷り込まれる。
 *   一度配布したら二度と変えられない。印刷物は回収できない（CLAUDE.md §9）。
 */
export const dynamic = 'force-dynamic'

export async function GET(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params

  const target = await getKakegamiForScan(id)
  if (!target) {
    // 掛け紙が見つからなくても来店者を行き止まりにしない
    return NextResponse.redirect(absoluteUrl('/'), { status: 307 })
  }

  await recordKakegamiScan({
    kakegamiId: target.id,
    referrer: request.headers.get('referer'),
    userAgent: request.headers.get('user-agent'),
    country: request.headers.get('x-vercel-ip-country'),
  })

  const response = NextResponse.redirect(absoluteUrl(`/kakegami/${target.koSlug}`), { status: 307 })
  response.headers.set('Cache-Control', 'no-store')
  return response
}
