import { createServerClient } from '@supabase/ssr'
import { createClient } from '@supabase/supabase-js'
import { cookies } from 'next/headers'
import type { Database } from '@/types/database'

const SCHEMA = 'koharubiyori'

function requireEnv(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`環境変数 ${name} が未設定です。.env.local を確認してください`)
  return value
}

/**
 * 公開ページ・管理画面から使うクライアント。
 * Cookie 経由でログインセッションを引き継ぐので、RLS がそのまま効く。
 */
export async function createSupabaseServerClient() {
  const cookieStore = await cookies()

  return createServerClient<Database, typeof SCHEMA>(
    requireEnv('NEXT_PUBLIC_SUPABASE_URL'),
    requireEnv('NEXT_PUBLIC_SUPABASE_ANON_KEY'),
    {
      db: { schema: SCHEMA },
      cookies: {
        getAll() {
          return cookieStore.getAll()
        },
        setAll(cookiesToSet) {
          try {
            for (const { name, value, options } of cookiesToSet) {
              cookieStore.set(name, value, options)
            }
          } catch {
            // Server Component からの呼び出しでは Cookie を書けない。
            // セッション更新は middleware 側で行うのでここは黙って捨ててよい
          }
        },
      },
    },
  )
}

/**
 * RLS を跨ぐ必要がある処理だけに使う（QRスキャンの記録など）。
 * ★ 作家の作品画像を外部AI APIに投げる用途に使わないこと（契約で学習利用を禁止している）
 */
export function createSupabaseServiceClient() {
  return createClient<Database, typeof SCHEMA>(
    requireEnv('NEXT_PUBLIC_SUPABASE_URL'),
    requireEnv('SUPABASE_SERVICE_ROLE_KEY'),
    {
      db: { schema: SCHEMA },
      auth: { persistSession: false, autoRefreshToken: false },
    },
  )
}
