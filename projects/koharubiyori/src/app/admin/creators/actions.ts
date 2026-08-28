'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { getAdminUser } from '@/lib/auth'
import {
  deleteCharacterScore,
  getCreatorById,
  insertCharacter,
  insertCreator,
  listCharactersWithScores,
  updateCreator,
  upsertCharacterScore,
} from '@/lib/koharu/queries'
import { isValidScore, judgeAll, tierForVerdict } from '@/lib/koharu/scoring'
import { formatJaDate, jstYmd } from '@/lib/koharu/date'
import type { Enums } from '@/types/database'

const TIERS: readonly Enums<'creator_tier'>[] = ['tier1', 'tier2', 'tier3']
const STATUSES: readonly Enums<'publish_status'>[] = ['draft', 'published', 'archived']
const HARE_MA: readonly Enums<'hare_ma'>[] = [
  'asa',
  'hitoiki',
  'yoru',
  'dekakeru',
  'kazaru',
  'sodateru',
]

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

function enumOrNull<T extends string>(
  formData: FormData,
  key: string,
  allowed: readonly T[],
): T | null {
  const value = str(formData, key)
  return (allowed as readonly string[]).includes(value) ? (value as T) : null
}

/** slug は URL に出る。ASCII の小文字とハイフンに限る */
function assertSlug(slug: string): string {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
    throw new Error('スラッグは英小文字・数字・ハイフンのみで入力してください')
  }
  return slug
}

// -------------------------------------------------------------
// 作家
// -------------------------------------------------------------

function creatorFieldsFrom(formData: FormData) {
  return {
    name: str(formData, 'name'),
    name_kana: nullable(formData, 'name_kana'),
    title: nullable(formData, 'title'),
    base_area: nullable(formData, 'base_area'),
    profile: nullable(formData, 'profile'),
    tsukumo_note: nullable(formData, 'tsukumo_note'),
    photo_url: nullable(formData, 'photo_url'),
    hero_image_url: nullable(formData, 'hero_image_url'),
    sns_x: nullable(formData, 'sns_x'),
    sns_instagram: nullable(formData, 'sns_instagram'),
    website_url: nullable(formData, 'website_url'),
    ec_url: nullable(formData, 'ec_url'),
    first_engaged_on: nullable(formData, 'first_engaged_on'),
    notes: nullable(formData, 'notes'),
    status: enumOrNull(formData, 'status', STATUSES) ?? 'draft',
  }
}

export async function createCreatorAction(formData: FormData) {
  await requireAdmin()

  const slug = assertSlug(str(formData, 'slug'))
  const fields = creatorFieldsFrom(formData)
  if (!fields.name) throw new Error('作家名は必須です')

  const creator = await insertCreator({ ...fields, slug })

  revalidatePath('/admin/creators')
  redirect(`/admin/creators/${creator.id}`)
}

export async function updateCreatorAction(formData: FormData) {
  await requireAdmin()

  const id = str(formData, 'id')
  if (!id) throw new Error('作家IDがありません')

  const slug = assertSlug(str(formData, 'slug'))
  const fields = creatorFieldsFrom(formData)
  if (!fields.name) throw new Error('作家名は必須です')

  await updateCreator(id, { ...fields, slug })

  revalidatePath('/admin/creators')
  revalidatePath(`/admin/creators/${id}`)
  revalidatePath(`/sakka/${slug}`)
}

// -------------------------------------------------------------
// キャラクター
// -------------------------------------------------------------

export async function createCharacterAction(formData: FormData) {
  await requireAdmin()

  const creatorId = str(formData, 'creator_id')
  const slug = assertSlug(str(formData, 'slug'))
  const name = str(formData, 'name')
  if (!creatorId || !name) throw new Error('作家とキャラクター名は必須です')

  await insertCharacter({
    creator_id: creatorId,
    slug,
    name,
    description: nullable(formData, 'description'),
    // 六つの晴れ間に翻訳できないキャラクターは登録しない（大原則・壱）
    hare_ma: enumOrNull(formData, 'hare_ma', HARE_MA),
    image_url: nullable(formData, 'image_url'),
    status: enumOrNull(formData, 'status', STATUSES) ?? 'draft',
  })

  revalidatePath(`/admin/creators/${creatorId}`)
}

// -------------------------------------------------------------
// 採点
// -------------------------------------------------------------

export async function saveScoreAction(formData: FormData) {
  await requireAdmin()

  const creatorId = str(formData, 'creator_id')
  const characterId = str(formData, 'character_id')
  const scorerName = str(formData, 'scorer_name')
  if (!characterId || !scorerName) throw new Error('キャラクターと採点者名は必須です')

  const score = {
    q1_line: intOrNull(formData, 'q1_line') ?? -1,
    q2_kurashi: intOrNull(formData, 'q2_kurashi') ?? -1,
    q3_koyomi: intOrNull(formData, 'q3_koyomi') ?? -1,
    q4_taigi: intOrNull(formData, 'q4_taigi') ?? -1,
  }

  for (const [key, value] of Object.entries(score)) {
    if (!isValidScore(value)) throw new Error(`${key} は 0〜5 で入力してください`)
  }

  await upsertCharacterScore({
    character_id: characterId,
    scorer_name: scorerName,
    ...score,
    comment: nullable(formData, 'comment'),
  })

  revalidatePath(`/admin/creators/${creatorId}`)
  revalidatePath('/admin/creators')
}

export async function deleteScoreAction(formData: FormData) {
  await requireAdmin()

  const creatorId = str(formData, 'creator_id')
  const scoreId = str(formData, 'score_id')
  if (!scoreId) throw new Error('採点IDがありません')

  await deleteCharacterScore(scoreId)

  revalidatePath(`/admin/creators/${creatorId}`)
  revalidatePath('/admin/creators')
}

/**
 * 判定を確定して作家の層を動かす。
 *
 * ★ 採点者2名未満では確定させない（CLAUDE.md §9）。
 * ★ 自動判定と違う層を入れるときは理由コメントを必須にする。
 */
export async function confirmTierAction(formData: FormData) {
  const user = await requireAdmin()

  const creatorId = str(formData, 'creator_id')
  const characterId = str(formData, 'character_id')
  if (!creatorId || !characterId) throw new Error('作家とキャラクターの指定がありません')

  const chosenTier = enumOrNull(formData, 'tier', TIERS)
  const reason = nullable(formData, 'reason')

  const characters = await listCharactersWithScores(creatorId)
  const target = characters.find((c) => c.character.id === characterId)
  if (!target) throw new Error('キャラクターが見つかりません')

  const judged = judgeAll(target.scores)

  if (judged.scorerCount < 2) {
    throw new Error('採点者が2名未満です。2名以上の採点が揃うまで確定できません')
  }

  const recommended = tierForVerdict(judged.verdict)
  const isOverride = chosenTier !== recommended

  if (isOverride && !reason) {
    throw new Error('自動判定と異なる層に確定するには、理由コメントが必須です')
  }

  const creator = await getCreatorById(creatorId)
  const stamp = formatJaDate(jstYmd())
  const logLine = isOverride
    ? `【${stamp}】${user.email} が自動判定(${judged.verdict ?? '—'} / 平均${judged.avgTotal})を上書きして ${chosenTier ?? '未起用'} に確定。理由: ${reason}`
    : `【${stamp}】${user.email} が判定どおり ${chosenTier ?? '未起用'} に確定（平均${judged.avgTotal}・採点者${judged.scorerCount}名）`

  await updateCreator(creatorId, {
    current_tier: chosenTier,
    notes: creator?.notes ? `${creator.notes}\n${logLine}` : logLine,
  })

  revalidatePath(`/admin/creators/${creatorId}`)
  revalidatePath('/admin/creators')
}
