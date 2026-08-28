import Link from 'next/link'
import { notFound, redirect } from 'next/navigation'
import { getAdminUser } from '@/lib/auth'
import { CreatorForm } from '@/components/koharu/creator-form'
import { ScoreSheet } from '@/components/koharu/score-sheet'
import {
  HARE_MA_LABELS,
  HARE_MA_ORDER,
  STATUS_LABELS,
  TIER_LABELS,
  VERDICT_LABELS,
  VERDICT_NOTES,
} from '@/lib/koharu/constants'
import { MAX_TOTAL, judgeAll, tierForVerdict } from '@/lib/koharu/scoring'
import { getCreatorById, listCharactersWithScores } from '@/lib/koharu/queries'
import type { Enums } from '@/types/database'
import {
  confirmTierAction,
  createCharacterAction,
  deleteScoreAction,
  saveScoreAction,
  updateCreatorAction,
} from '../actions'

type Props = { params: Promise<{ id: string }> }

const TIERS: Enums<'creator_tier'>[] = ['tier1', 'tier2', 'tier3']

export const metadata = { title: '作家の編集' }

export default async function EditCreatorPage({ params }: Props) {
  const user = await getAdminUser()
  if (!user) redirect('/admin/login')

  const { id } = await params
  const creator = await getCreatorById(id)
  if (!creator) notFound()

  const characters = await listCharactersWithScores(creator.id)

  return (
    <main className="mx-auto w-full max-w-[880px] px-5 py-10 sm:px-6">
      <nav className="text-[12px] text-sumi-55">
        <Link href="/admin/creators" className="hover:text-hare">
          作家
        </Link>
        <span className="px-1.5">／</span>
        <span>{creator.name}</span>
      </nav>

      <div className="mt-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[26px]">{creator.name}</h1>
          <p className="mt-1 text-[12px] text-sumi-55">
            {STATUS_LABELS[creator.status]}
            {creator.current_tier ? `・${TIER_LABELS[creator.current_tier]}` : '・未起用'}
          </p>
        </div>
        {creator.status === 'published' ? (
          <Link
            href={`/sakka/${creator.slug}`}
            className="text-[13px] text-hare underline-offset-4 hover:underline"
          >
            公開ページを見る →
          </Link>
        ) : null}
      </div>

      {/* --------------------------------------------------------
          キャラクターと四問テスト
          -------------------------------------------------------- */}
      <section className="mt-12">
        <h2 className="text-[20px]">キャラクターと四問テスト</h2>

        {characters.length === 0 ? (
          <p className="mt-3 text-[13px] text-sumi-55">
            まだキャラクターがありません。下のフォームから登録してください。
          </p>
        ) : (
          <div className="mt-6 space-y-12">
            {characters.map(({ character, scores }) => {
              const judged = judgeAll(scores)
              const recommended = tierForVerdict(judged.verdict)

              return (
                <div key={character.id} className="border-t border-line pt-6">
                  <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                    <h3 className="font-mincho text-[19px]">{character.name}</h3>
                    <span className="text-[12px] text-sumi-55">
                      {character.hare_ma ? HARE_MA_LABELS[character.hare_ma] : '晴れ間 未設定'}
                      ・{STATUS_LABELS[character.status]}
                    </span>
                  </div>

                  {/* 判定 */}
                  <div className="mt-4 border border-line bg-washi-shade/60 px-4 py-4">
                    {judged.verdict === null ? (
                      <p className="text-[13px] text-sumi-55">まだ採点がありません。</p>
                    ) : (
                      <>
                        <p className="text-[15px]">
                          判定：
                          <span className="font-mincho text-[20px]">
                            {VERDICT_LABELS[judged.verdict]}
                          </span>
                          <span className="tabular pl-3 text-[13px] text-sumi-70">
                            平均 {judged.avgTotal} / {MAX_TOTAL}・採点者 {judged.scorerCount}名
                          </span>
                        </p>
                        <p className="mt-1 text-[12px] text-sumi-55">
                          {VERDICT_NOTES[judged.verdict]}
                        </p>
                        {judged.minQ3 === 0 ? (
                          <p className="mt-2 text-[13px] text-hare">
                            採点者の誰かが第三問「暦」に0点を付けています。足切りで見送りです。
                          </p>
                        ) : null}
                        {!judged.isConfirmable ? (
                          <p className="mt-2 border border-hare/40 bg-hare/8 px-3 py-2 text-[13px] text-hare">
                            採点者が{judged.scorerCount}名です。2名以上の採点が揃うまで確定できません。
                          </p>
                        ) : null}
                      </>
                    )}
                  </div>

                  {/* 確定（採点者2名以上のときだけ出す） */}
                  {judged.isConfirmable ? (
                    <form
                      action={confirmTierAction}
                      className="mt-4 border border-line bg-white px-4 py-4"
                    >
                      <input type="hidden" name="creator_id" value={creator.id} />
                      <input type="hidden" name="character_id" value={character.id} />
                      <p className="text-[13px] text-sumi-70">
                        判定を確定して作家の層を決める
                        {recommended ? (
                          <span className="pl-2 text-[12px] text-sumi-55">
                            （自動判定は {TIER_LABELS[recommended]}）
                          </span>
                        ) : (
                          <span className="pl-2 text-[12px] text-sumi-55">
                            （自動判定は 起用しない）
                          </span>
                        )}
                      </p>
                      <div className="mt-3 flex flex-wrap items-center gap-3">
                        <select
                          name="tier"
                          defaultValue={recommended ?? ''}
                          aria-label="確定する層"
                          className="border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
                        >
                          <option value="">起用しない</option>
                          {TIERS.map((t) => (
                            <option key={t} value={t}>
                              {TIER_LABELS[t]}
                            </option>
                          ))}
                        </select>
                        <input
                          name="reason"
                          placeholder="自動判定と違う層にするなら理由（必須）"
                          className="min-w-[260px] flex-1 border border-line px-3 py-2 text-[14px] outline-none focus:border-hare"
                        />
                        <button
                          type="submit"
                          className="bg-sumi px-4 py-2.5 text-[14px] text-washi hover:opacity-85"
                        >
                          確定する
                        </button>
                      </div>
                    </form>
                  ) : null}

                  {/* 採点一覧 */}
                  {scores.length > 0 ? (
                    <div className="mt-6 overflow-x-auto">
                      <table className="w-full min-w-[620px] border-collapse text-[13px]">
                        <thead>
                          <tr className="border-y border-line text-left text-[12px] text-sumi-55">
                            <th className="py-2 pr-4 font-normal">採点者</th>
                            <th className="py-2 pr-3 text-right font-normal">一・線</th>
                            <th className="py-2 pr-3 text-right font-normal">二・暮らし</th>
                            <th className="py-2 pr-3 text-right font-normal">三・暦</th>
                            <th className="py-2 pr-3 text-right font-normal">四・大義</th>
                            <th className="py-2 pr-4 text-right font-normal">合計</th>
                            <th className="py-2 pr-4 font-normal">コメント</th>
                            <th className="py-2 font-normal" />
                          </tr>
                        </thead>
                        <tbody>
                          {scores.map((s) => (
                            <tr key={s.id} className="border-b border-line align-top">
                              <td className="py-2.5 pr-4">{s.scorer_name}</td>
                              <td className="tabular py-2.5 pr-3 text-right">{s.q1_line}</td>
                              <td className="tabular py-2.5 pr-3 text-right">{s.q2_kurashi}</td>
                              <td
                                className={`tabular py-2.5 pr-3 text-right ${s.q3_koyomi === 0 ? 'text-hare' : ''}`}
                              >
                                {s.q3_koyomi}
                              </td>
                              <td className="tabular py-2.5 pr-3 text-right">{s.q4_taigi}</td>
                              <td className="tabular py-2.5 pr-4 text-right">{s.total}</td>
                              <td className="py-2.5 pr-4 text-sumi-70">{s.comment ?? '—'}</td>
                              <td className="py-2.5 text-right">
                                <form action={deleteScoreAction}>
                                  <input type="hidden" name="creator_id" value={creator.id} />
                                  <input type="hidden" name="score_id" value={s.id} />
                                  <button
                                    type="submit"
                                    className="text-[12px] text-sumi-55 hover:text-hare"
                                  >
                                    削除
                                  </button>
                                </form>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  <div className="mt-6">
                    <ScoreSheet
                      creatorId={creator.id}
                      characterId={character.id}
                      action={saveScoreAction}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* キャラクターの追加 */}
        <form action={createCharacterAction} className="mt-10 border border-line bg-white p-5">
          <input type="hidden" name="creator_id" value={creator.id} />
          <h3 className="text-[16px]">キャラクターを追加する</h3>
          <p className="mt-1 text-[12px] text-sumi-55">
            編集軸が先、キャラクターが後。六つの晴れ間に翻訳できないものは登録しない。
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="char-name" className="block text-[13px] text-sumi-70">
                名前 <span className="text-hare">*</span>
              </label>
              <input
                id="char-name"
                name="name"
                required
                className="mt-1.5 w-full border border-line px-3 py-2 text-[14px] outline-none focus:border-hare"
              />
            </div>
            <div>
              <label htmlFor="char-slug" className="block text-[13px] text-sumi-70">
                スラッグ <span className="text-hare">*</span>
              </label>
              <input
                id="char-slug"
                name="slug"
                required
                className="mt-1.5 w-full border border-line px-3 py-2 text-[14px] outline-none focus:border-hare"
              />
            </div>
            <div>
              <label htmlFor="char-hare-ma" className="block text-[13px] text-sumi-70">
                住む晴れ間
              </label>
              <select
                id="char-hare-ma"
                name="hare_ma"
                defaultValue=""
                className="mt-1.5 w-full border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
              >
                <option value="">未設定</option>
                {HARE_MA_ORDER.map((h) => (
                  <option key={h} value={h}>
                    {HARE_MA_LABELS[h]}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="char-image" className="block text-[13px] text-sumi-70">
                画像URL
              </label>
              <input
                id="char-image"
                name="image_url"
                className="mt-1.5 w-full border border-line px-3 py-2 text-[14px] outline-none focus:border-hare"
              />
            </div>
          </div>
          <div className="mt-4">
            <label htmlFor="char-description" className="block text-[13px] text-sumi-70">
              説明
            </label>
            <textarea
              id="char-description"
              name="description"
              rows={3}
              className="mt-1.5 w-full border border-line px-3 py-2 text-[14px] outline-none focus:border-hare"
            />
          </div>
          <button
            type="submit"
            className="mt-5 border border-sumi px-5 py-2.5 text-[14px] hover:bg-washi-shade"
          >
            追加する
          </button>
        </form>
      </section>

      {/* --------------------------------------------------------
          作家情報
          -------------------------------------------------------- */}
      <section className="mt-16 border-t border-line pt-8">
        <h2 className="text-[20px]">作家情報</h2>
        <div className="mt-6">
          <CreatorForm action={updateCreatorAction} creator={creator} submitLabel="保存する" />
        </div>
      </section>
    </main>
  )
}
