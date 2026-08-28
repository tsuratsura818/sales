import { NextResponse, type NextRequest } from 'next/server'
import { createSupabaseServerClient } from '@/lib/supabase/server'
import { isAllowedAdminEmail } from '@/lib/auth'

/** メールリンク（Magic Link）の着地点 */
export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get('code')
  const next = request.nextUrl.searchParams.get('next') ?? '/admin'

  if (!code) {
    return NextResponse.redirect(new URL('/admin/login?error=missing_code', request.url))
  }

  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase.auth.exchangeCodeForSession(code)

  if (error || !isAllowedAdminEmail(data.user?.email)) {
    await supabase.auth.signOut()
    return NextResponse.redirect(new URL('/admin/login?error=not_allowed', request.url))
  }

  return NextResponse.redirect(new URL(next, request.url))
}
