'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { getAdminUser } from '@/lib/auth'
import { insertKakegami, updateKakegami } from '@/lib/koharu/queries'
import type { Enums } from '@/types/database'

const STATUSES: readonly Enums<'publish_status'>[] = ['draft', 'published', 'archived']

async function requireAdmin() {
  const user = await getAdminUser()
  if (!user) redirect('/admin/login')
  return user
}

function str(formData: FormData, key: string): string {
  return String(formData.get(key) ?? '').trim()
}

function nullable(formData: FormData, key: string): string | null {
  const value = str(formData, key)
  return value === '' ? null : value
}

function intOrNull(formData: FormData, key: string): number | null {
  const value = str(formData, key)
  if (value === '') return null
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) ? parsed : null
}

function statusOf(formData: FormData): Enums<'publish_status'> {
  const value = str(formData, 'status')
  return (STATUSES as readonly string[]).includes(value)
    ? (value as Enums<'publish_status'>)
    : 'draft'
}

export async function createKakegamiAction(formData: FormData) {
  await requireAdmin()

  const koId = intOrNull(formData, 'ko_id')
  const issueDate = str(formData, 'issue_date')
  if (koId === null) throw new Error('候を選んでください')
  // issue_date は JST の日付として入力される。ここで Date に変換しないこと
  if (!/^\d{4}-\d{2}-\d{2}$/.test(issueDate)) throw new Error('発行日を入力してください')

  await insertKakegami({
    ko_id: koId,
    creator_id: nullable(formData, 'creator_id'),
    issue_date: issueDate,
    artwork_url: nullable(formData, 'artwork_url'),
    print_qty: intOrNull(formData, 'print_qty'),
    distributed_qty: intOrNull(formData, 'distributed_qty'),
    status: statusOf(formData),
    notes: nullable(formData, 'notes'),
  })

  revalidatePath('/admin/kakegami')
  redirect('/admin/kakegami')
}

/** 配布実績はあとから入る。スキャン率はこの数字で決まる */
export async function updateDistributedAction(formData: FormData) {
  await requireAdmin()

  const id = str(formData, 'id')
  if (!id) throw new Error('掛け紙IDがありません')

  await updateKakegami(id, {
    distributed_qty: intOrNull(formData, 'distributed_qty'),
    status: statusOf(formData),
  })

  revalidatePath('/admin/kakegami')
}
