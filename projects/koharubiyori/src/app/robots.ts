import type { MetadataRoute } from 'next'
import { absoluteUrl } from '@/lib/site'

/**
 * AIクローラーを明示的に許可する（CLAUDE.md §6 AEO）。
 * 管理画面と QR 着地点だけは除外する。
 */
const AI_CRAWLERS = [
  'GPTBot',
  'OAI-SearchBot',
  'ChatGPT-User',
  'ClaudeBot',
  'Claude-User',
  'Claude-SearchBot',
  'PerplexityBot',
  'Perplexity-User',
  'Google-Extended',
  'Applebot-Extended',
  'CCBot',
  'Bytespider',
]

const DISALLOW = ['/admin', '/auth', '/qr']

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: '*', allow: '/', disallow: DISALLOW },
      ...AI_CRAWLERS.map((userAgent) => ({ userAgent, allow: '/', disallow: DISALLOW })),
    ],
    sitemap: absoluteUrl('/sitemap.xml'),
  }
}
