/** サイト共通設定。QR・OGP・構造化データの絶対URL生成に使う */

export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000').replace(
  /\/$/,
  '',
)

export function absoluteUrl(path: string): string {
  return `${SITE_URL}${path.startsWith('/') ? path : `/${path}`}`
}

/**
 * 掛け紙裏QRの遷移先。
 * **一度刷ったらこのURLスキームは変えられない。**印刷物は回収できない（CLAUDE.md §9）。
 */
export function qrUrl(kakegamiId: string): string {
  return absoluteUrl(`/qr/${kakegamiId}`)
}
