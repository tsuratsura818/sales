import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getAdminUser } from '@/lib/auth'
import { CreatorForm } from '@/components/koharu/creator-form'
import { createCreatorAction } from '../actions'

export const metadata = { title: '作家を登録' }

export default async function NewCreatorPage() {
  const user = await getAdminUser()
  if (!user) redirect('/admin/login')

  return (
    <main className="mx-auto w-full max-w-[820px] px-5 py-10 sm:px-6">
      <nav className="text-[12px] text-sumi-55">
        <Link href="/admin/creators" className="hover:text-hare">
          作家
        </Link>
        <span className="px-1.5">／</span>
        <span>新規登録</span>
      </nav>

      <h1 className="mt-6 text-[24px]">作家を登録する</h1>
      <p className="mt-2 text-[13px] text-sumi-55">
        登録したあと、キャラクターを足して四問テストの採点に進みます。
      </p>

      <div className="mt-8">
        <CreatorForm action={createCreatorAction} submitLabel="登録する" />
      </div>
    </main>
  )
}
