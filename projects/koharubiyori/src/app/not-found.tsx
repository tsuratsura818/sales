import Link from 'next/link'
import { BRAND_NAME } from '@/lib/koharu/constants'

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[560px] flex-col justify-center px-5 py-24 sm:px-6">
      <h1 className="text-[26px]">お探しのページは見つかりませんでした</h1>
      <p className="mt-4 text-[14px] leading-[1.9] text-sumi-70">
        掛け紙のQRから来られた方は、お手数ですがもう一度読み取ってみてください。
      </p>
      <Link href="/" className="mt-8 text-[14px] text-hare underline-offset-4 hover:underline">
        {BRAND_NAME}のトップへ →
      </Link>
    </main>
  )
}
