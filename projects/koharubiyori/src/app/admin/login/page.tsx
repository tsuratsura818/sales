import { createSupabaseServerClient } from '@/lib/supabase/server'
import { isAllowedAdminEmail } from '@/lib/auth'
import { absoluteUrl } from '@/lib/site'
import { redirect } from 'next/navigation'

export const metadata = { title: '管理画面ログイン', robots: { index: false } }

const ERROR_MESSAGES: Record<string, string> = {
  missing_code: 'リンクが正しくありません。もう一度お試しください。',
  not_allowed: 'このメールアドレスには管理画面の権限がありません。',
  send_failed: 'メールの送信に失敗しました。時間をおいてお試しください。',
  not_allowed_email: 'このメールアドレスは許可リストにありません。',
}

async function sendMagicLink(formData: FormData) {
  'use server'

  const email = String(formData.get('email') ?? '').trim()
  const next = String(formData.get('next') ?? '/admin')

  // 許可リストにないアドレスにはリンク自体を送らない
  if (!isAllowedAdminEmail(email)) {
    redirect('/admin/login?error=not_allowed_email')
  }

  const supabase = await createSupabaseServerClient()
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: {
      emailRedirectTo: absoluteUrl(`/auth/callback?next=${encodeURIComponent(next)}`),
      shouldCreateUser: true,
    },
  })

  if (error) redirect('/admin/login?error=send_failed')
  redirect('/admin/login?sent=1')
}

export default async function AdminLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; sent?: string; next?: string }>
}) {
  const { error, sent, next } = await searchParams

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[420px] flex-col justify-center px-5 py-16">
      <h1 className="text-[24px]">管理画面</h1>
      <p className="mt-2 text-[13px] text-sumi-55">
        許可されたメールアドレスにログインリンクを送ります。
      </p>

      {sent ? (
        <p className="mt-6 border border-hare/40 bg-hare/8 px-4 py-3 text-[13px] text-hare">
          ログインリンクを送りました。メールを確認してください。
        </p>
      ) : null}

      {error ? (
        <p className="mt-6 border border-line bg-washi-shade px-4 py-3 text-[13px]">
          {ERROR_MESSAGES[error] ?? 'ログインに失敗しました。'}
        </p>
      ) : null}

      <form action={sendMagicLink} className="mt-8">
        <input type="hidden" name="next" value={next ?? '/admin'} />
        <label htmlFor="email" className="block text-[13px] text-sumi-70">
          メールアドレス
        </label>
        <input
          id="email"
          name="email"
          type="email"
          required
          autoComplete="email"
          className="mt-2 w-full border border-line bg-white px-3 py-2.5 text-[15px] outline-none focus:border-hare"
        />
        <button
          type="submit"
          className="mt-5 w-full bg-sumi px-4 py-3 text-[14px] text-washi transition-opacity hover:opacity-85"
        >
          ログインリンクを送る
        </button>
      </form>
    </main>
  )
}
