import 'server-only'
import { createSupabaseServerClient, createSupabaseServiceClient } from '@/lib/supabase/server'
import type { Enums, Tables, TablesInsert, Views } from '@/types/database'

/**
 * Supabase クエリはすべてここに集約する。
 * ページ／コンポーネントから supabase.from() を直接呼ばないこと（CLAUDE.md §8）。
 */

export type Creator = Tables<'creators'>
export type Character = Tables<'characters'>
export type CharacterScore = Tables<'character_scores'>
export type Kakegami = Tables<'kakegami'>
export type KoyomiKo = Tables<'koyomi_ko'>
export type CharacterVerdict = Views<'character_verdicts'>
export type KakegamiStats = Views<'kakegami_stats'>

function fail(context: string, error: { message: string } | null): never {
  throw new Error(`${context}: ${error?.message ?? 'unknown error'}`)
}

// -------------------------------------------------------------
// 公開ページ
// -------------------------------------------------------------

/** /sakka/[slug]。published 以外は null（呼び出し側で 404 にする） */
export async function getPublishedCreatorBySlug(slug: string): Promise<Creator | null> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase
    .from('creators')
    .select('*')
    .eq('slug', slug)
    .eq('status', 'published')
    .maybeSingle()

  if (error) fail('作家の取得に失敗しました', error)
  return data
}

/** /sakka 一覧。公開中の作家のみ */
export async function listPublishedCreators(): Promise<Creator[]> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase
    .from('creators')
    .select('*')
    .eq('status', 'published')
    .order('name')

  if (error) fail('公開作家一覧の取得に失敗しました', error)
  return data ?? []
}

export async function listPublishedCreatorSlugs(): Promise<string[]> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase.from('creators').select('slug').eq('status', 'published')

  if (error) fail('公開作家一覧の取得に失敗しました', error)
  return (data ?? []).map((row) => row.slug)
}

export type CreatorKakegami = Kakegami & { ko: KoyomiKo | null }

/** その作家が描いた掛け紙を新しい順に */
export async function listPublishedKakegamiByCreator(creatorId: string): Promise<CreatorKakegami[]> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase
    .from('kakegami')
    .select('*, ko:koyomi_ko(*)')
    .eq('creator_id', creatorId)
    .eq('status', 'published')
    .order('issue_date', { ascending: false })

  if (error) fail('掛け紙の取得に失敗しました', error)
  return (data ?? []) as CreatorKakegami[]
}

export async function listPublishedCharactersByCreator(creatorId: string): Promise<Character[]> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase
    .from('characters')
    .select('*')
    .eq('creator_id', creatorId)
    .eq('status', 'published')
    .order('created_at', { ascending: true })

  if (error) fail('キャラクターの取得に失敗しました', error)
  return data ?? []
}

export async function getKoBySlug(slug: string): Promise<KoyomiKo | null> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase
    .from('koyomi_ko')
    .select('*')
    .eq('slug', slug)
    .maybeSingle()

  if (error) fail('候の取得に失敗しました', error)
  return data
}

export async function listKo(): Promise<KoyomiKo[]> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase.from('koyomi_ko').select('*').order('id')

  if (error) fail('七十二候マスタの取得に失敗しました', error)
  return data ?? []
}

export type KakegamiWithCreator = Kakegami & { creator: Creator | null; character: Character | null }

/** /kakegami/[ko]。その候の掛け紙を新しい順に */
export async function listPublishedKakegamiByKo(koId: number): Promise<KakegamiWithCreator[]> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase
    .from('kakegami')
    .select('*, creator:creators(*), character:characters(*)')
    .eq('ko_id', koId)
    .eq('status', 'published')
    .order('issue_date', { ascending: false })

  if (error) fail('候の掛け紙の取得に失敗しました', error)
  return (data ?? []) as KakegamiWithCreator[]
}

// -------------------------------------------------------------
// QRスキャン計測
// -------------------------------------------------------------

/** QR着地時に掛け紙 → 候スラッグを引く。draft でもリダイレクト先は返す */
export async function getKakegamiForScan(
  kakegamiId: string,
): Promise<{ id: string; koSlug: string } | null> {
  const supabase = createSupabaseServiceClient()
  const { data, error } = await supabase
    .from('kakegami')
    .select('id, ko:koyomi_ko(slug)')
    .eq('id', kakegamiId)
    .maybeSingle()

  if (error) fail('掛け紙の取得に失敗しました', error)
  if (!data) return null

  const ko = data.ko as unknown as { slug: string } | null
  if (!ko) return null
  return { id: data.id, koSlug: ko.slug }
}

/**
 * スキャンを1件記録する。
 * 来店者を追跡しない: 保存するのは referrer / UA / 国のみで、IP も識別子も残さない。
 */
export async function recordKakegamiScan(input: {
  kakegamiId: string
  referrer: string | null
  userAgent: string | null
  country: string | null
}): Promise<void> {
  const supabase = createSupabaseServiceClient()
  const { error } = await supabase.from('kakegami_scans').insert({
    kakegami_id: input.kakegamiId,
    referrer: input.referrer,
    user_agent: input.userAgent,
    country: input.country,
  })

  // 計測に失敗しても来店者の遷移は止めない
  if (error) console.error('[kakegami_scans] insert failed:', error.message)
}

// -------------------------------------------------------------
// 管理画面: 作家
// -------------------------------------------------------------

export type AdminCreatorRow = {
  creator: Creator
  characterCount: number
  /** その作家のキャラクターのうち最も高い平均点 */
  bestAvgTotal: number | null
  bestVerdict: Enums<'score_verdict'> | null
  bestScorerCount: number
  /** 採点者2名以上に達しているか */
  isConfirmable: boolean
  lastEngagedOn: string | null
  kakegamiCount: number
}

/** 一覧。合計点の降順（未採点は末尾） */
export async function listCreatorsForAdmin(): Promise<AdminCreatorRow[]> {
  const supabase = await createSupabaseServerClient()

  const [creatorsRes, charactersRes, verdictsRes, kakegamiRes] = await Promise.all([
    supabase.from('creators').select('*').order('created_at', { ascending: false }),
    supabase.from('characters').select('id, creator_id'),
    supabase.from('character_verdicts').select('*'),
    supabase.from('kakegami').select('creator_id, issue_date'),
  ])

  if (creatorsRes.error) fail('作家一覧の取得に失敗しました', creatorsRes.error)
  if (charactersRes.error) fail('キャラクター一覧の取得に失敗しました', charactersRes.error)
  if (verdictsRes.error) fail('判定の取得に失敗しました', verdictsRes.error)
  if (kakegamiRes.error) fail('掛け紙一覧の取得に失敗しました', kakegamiRes.error)

  const verdictByCharacter = new Map<string, CharacterVerdict>()
  for (const v of verdictsRes.data ?? []) {
    if (v.character_id) verdictByCharacter.set(v.character_id, v)
  }

  const charactersByCreator = new Map<string, string[]>()
  for (const c of charactersRes.data ?? []) {
    const list = charactersByCreator.get(c.creator_id) ?? []
    list.push(c.id)
    charactersByCreator.set(c.creator_id, list)
  }

  const kakegamiByCreator = new Map<string, string[]>()
  for (const k of kakegamiRes.data ?? []) {
    if (!k.creator_id) continue
    const list = kakegamiByCreator.get(k.creator_id) ?? []
    list.push(k.issue_date)
    kakegamiByCreator.set(k.creator_id, list)
  }

  const rows: AdminCreatorRow[] = (creatorsRes.data ?? []).map((creator) => {
    const characterIds = charactersByCreator.get(creator.id) ?? []
    const issueDates = kakegamiByCreator.get(creator.id) ?? []

    let best: CharacterVerdict | null = null
    for (const id of characterIds) {
      const v = verdictByCharacter.get(id)
      if (!v || v.avg_total === null) continue
      if (best === null || (best.avg_total ?? -1) < v.avg_total) best = v
    }

    return {
      creator,
      characterCount: characterIds.length,
      bestAvgTotal: best?.avg_total ?? null,
      bestVerdict: best?.verdict ?? null,
      bestScorerCount: best?.scorer_count ?? 0,
      isConfirmable: best?.is_confirmable ?? false,
      lastEngagedOn: issueDates.length > 0 ? issueDates.slice().sort().at(-1) ?? null : null,
      kakegamiCount: issueDates.length,
    }
  })

  // 合計点の降順。未採点（null）は末尾に落とす
  rows.sort((a, b) => {
    if (a.bestAvgTotal === null && b.bestAvgTotal === null) return 0
    if (a.bestAvgTotal === null) return 1
    if (b.bestAvgTotal === null) return -1
    return b.bestAvgTotal - a.bestAvgTotal
  })

  return rows
}

export async function getCreatorById(id: string): Promise<Creator | null> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase.from('creators').select('*').eq('id', id).maybeSingle()

  if (error) fail('作家の取得に失敗しました', error)
  return data
}

export async function insertCreator(input: TablesInsert<'creators'>): Promise<Creator> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase.from('creators').insert(input).select('*').single()

  if (error) fail('作家の登録に失敗しました', error)
  return data
}

export async function updateCreator(
  id: string,
  patch: Partial<TablesInsert<'creators'>>,
): Promise<void> {
  const supabase = await createSupabaseServerClient()
  const { error } = await supabase.from('creators').update(patch).eq('id', id)

  if (error) fail('作家の更新に失敗しました', error)
}

// -------------------------------------------------------------
// 管理画面: キャラクターと採点
// -------------------------------------------------------------

export type CharacterWithScores = {
  character: Character
  scores: CharacterScore[]
  verdict: CharacterVerdict | null
}

export async function listCharactersWithScores(creatorId: string): Promise<CharacterWithScores[]> {
  const supabase = await createSupabaseServerClient()

  const { data: characters, error: charError } = await supabase
    .from('characters')
    .select('*')
    .eq('creator_id', creatorId)
    .order('created_at', { ascending: true })

  if (charError) fail('キャラクターの取得に失敗しました', charError)
  if (!characters || characters.length === 0) return []

  const ids = characters.map((c) => c.id)

  const [scoresRes, verdictsRes] = await Promise.all([
    supabase
      .from('character_scores')
      .select('*')
      .in('character_id', ids)
      .order('scored_at', { ascending: true }),
    supabase.from('character_verdicts').select('*').in('character_id', ids),
  ])

  if (scoresRes.error) fail('採点の取得に失敗しました', scoresRes.error)
  if (verdictsRes.error) fail('判定の取得に失敗しました', verdictsRes.error)

  return characters.map((character) => ({
    character,
    scores: (scoresRes.data ?? []).filter((s) => s.character_id === character.id),
    verdict: (verdictsRes.data ?? []).find((v) => v.character_id === character.id) ?? null,
  }))
}

export async function insertCharacter(input: TablesInsert<'characters'>): Promise<Character> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase.from('characters').insert(input).select('*').single()

  if (error) fail('キャラクターの登録に失敗しました', error)
  return data
}

/** 採点は (character_id, scorer_name) で一意。同じ採点者は上書きする */
export async function upsertCharacterScore(input: TablesInsert<'character_scores'>): Promise<void> {
  const supabase = await createSupabaseServerClient()
  const { error } = await supabase
    .from('character_scores')
    .upsert(input, { onConflict: 'character_id,scorer_name' })

  if (error) fail('採点の保存に失敗しました', error)
}

export async function deleteCharacterScore(id: string): Promise<void> {
  const supabase = await createSupabaseServerClient()
  const { error } = await supabase.from('character_scores').delete().eq('id', id)

  if (error) fail('採点の削除に失敗しました', error)
}

// -------------------------------------------------------------
// 管理画面: 掛け紙
// -------------------------------------------------------------

export type AdminKakegamiRow = {
  kakegami: Kakegami
  ko: KoyomiKo | null
  creator: Creator | null
  scanCount: number
  scanRatePct: number | null
}

export async function listKakegamiForAdmin(): Promise<AdminKakegamiRow[]> {
  const supabase = await createSupabaseServerClient()

  const [kakegamiRes, statsRes] = await Promise.all([
    supabase
      .from('kakegami')
      .select('*, ko:koyomi_ko(*), creator:creators(*)')
      .order('issue_date', { ascending: false }),
    supabase.from('kakegami_stats').select('*'),
  ])

  if (kakegamiRes.error) fail('掛け紙一覧の取得に失敗しました', kakegamiRes.error)
  if (statsRes.error) fail('スキャン集計の取得に失敗しました', statsRes.error)

  const statsById = new Map<string, KakegamiStats>()
  for (const s of statsRes.data ?? []) {
    if (s.kakegami_id) statsById.set(s.kakegami_id, s)
  }

  type Joined = Kakegami & { ko: KoyomiKo | null; creator: Creator | null }

  return ((kakegamiRes.data ?? []) as Joined[]).map((row) => {
    const { ko, creator, ...kakegami } = row
    const stats = statsById.get(kakegami.id)
    return {
      kakegami,
      ko,
      creator,
      scanCount: stats?.scan_count ?? 0,
      scanRatePct: stats?.scan_rate_pct ?? null,
    }
  })
}

export async function insertKakegami(input: TablesInsert<'kakegami'>): Promise<Kakegami> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase.from('kakegami').insert(input).select('*').single()

  if (error) fail('掛け紙の登録に失敗しました', error)
  return data
}

export async function updateKakegami(
  id: string,
  patch: Partial<TablesInsert<'kakegami'>>,
): Promise<void> {
  const supabase = await createSupabaseServerClient()
  const { error } = await supabase.from('kakegami').update(patch).eq('id', id)

  if (error) fail('掛け紙の更新に失敗しました', error)
}

/** 掛け紙の発行登録フォームで使う、作家の選択肢 */
export async function listCreatorOptions(): Promise<Pick<Creator, 'id' | 'name'>[]> {
  const supabase = await createSupabaseServerClient()
  const { data, error } = await supabase.from('creators').select('id, name').order('name')

  if (error) fail('作家の選択肢の取得に失敗しました', error)
  return data ?? []
}
