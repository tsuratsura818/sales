import Link from 'next/link'
import { BRAND_NAME } from '@/lib/koharu/constants'

export const metadata = { robots: { index: false, follow: false } }

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh">
      <header className="border-b border-line">
        <div className="mx-auto flex w-full max-w-[1080px] flex-wrap items-center gap-x-6 gap-y-2 px-5 py-4 sm:px-6">
          <Link href="/admin" className="font-mincho text-[17px]">
            {BRAND_NAME}　管理
          </Link>
          <nav className="flex gap-5 text-[13px] text-sumi-70">
            <Link href="/admin/creators" className="hover:text-hare">
              作家
            </Link>
            <Link href="/admin/kakegami" className="hover:text-hare">
              掛け紙
            </Link>
          </nav>
        </div>
      </header>
      {children}
    </div>
  )
}
