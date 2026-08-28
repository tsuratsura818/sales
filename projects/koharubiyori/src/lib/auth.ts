import { createSupabaseServerClient } from '@/lib/supabase/server'

/**
 * 管理画面の認証。
 * Supabase Auth のメールリンク（Magic Link）＋許可メールの突き合わせという最小構成。
 * 運用が固まったら core スキーマのロール判定に差し替える。
 */

export function allowedAdminEmails(): string[] {
  return (process.env.ADMIN_ALLOWED_EMAILS ?? '')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
}

export function isAllowedAdminEmail(email: string | null | undefined): boolean {
  if (!email) return false
  const allowed = allowedAdminEmails()
  // 未設定のまま本番に出すと管理画面が誰でも開けてしまうので、空リストは全拒否にする
  if (allowed.length === 0) return false
  return allowed.includes(email.toLowerCase())
}

export type AdminUser = { id: string; email: string }

export async function getAdminUser(): Promise<AdminUser | null> {
  const supabase = await createSupabaseServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user?.email || !isAllowedAdminEmail(user.email)) return null
  return { id: user.id, email: user.email }
}
