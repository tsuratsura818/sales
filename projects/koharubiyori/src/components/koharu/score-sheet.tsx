'use client'

import { useState } from 'react'
import { SCORE_QUESTIONS, VERDICT_LABELS, VERDICT_NOTES } from '@/lib/koharu/constants'
import { MAX_PER_QUESTION, MAX_TOTAL, judgeOne, type ScoreInput } from '@/lib/koharu/scoring'

type Props = {
  creatorId: string
  characterId: string
  action: (formData: FormData) => void
  /** 既存の採点を読み込んで上書きするとき */
  initial?: (ScoreInput & { scorer_name: string; comment: string | null }) | undefined
}

const EMPTY: ScoreInput = { q1_line: 0, q2_kurashi: 0, q3_koyomi: 0, q4_taigi: 0 }

/**
 * 四問テストの採点フォーム。
 * ここに出るのは単票のプレビュー判定。確定判定は採点者全員ぶんで出す。
 */
export function ScoreSheet({ creatorId, characterId, action, initial }: Props) {
  const [score, setScore] = useState<ScoreInput>(
    initial
      ? {
          q1_line: initial.q1_line,
          q2_kurashi: initial.q2_kurashi,
          q3_koyomi: initial.q3_koyomi,
          q4_taigi: initial.q4_taigi,
        }
      : EMPTY,
  )

  const total = score.q1_line + score.q2_kurashi + score.q3_koyomi + score.q4_taigi
  const preview = judgeOne(score)
  const isCutOff = score.q3_koyomi === 0

  return (
    <form action={action} className="border border-line bg-white p-5">
      <input type="hidden" name="creator_id" value={creatorId} />
      <input type="hidden" name="character_id" value={characterId} />

      <div>
        <label htmlFor={`scorer-${characterId}`} className="block text-[13px] text-sumi-70">
          採点者名（同じ名前で保存すると上書きになります）
        </label>
        <input
          id={`scorer-${characterId}`}
          name="scorer_name"
          required
          defaultValue={initial?.scorer_name ?? ''}
          className="mt-1.5 w-full max-w-[280px] border border-line px-3 py-2 text-[14px] outline-none focus:border-hare"
        />
      </div>

      <div className="mt-6 space-y-5">
        {SCORE_QUESTIONS.map((q) => {
          const value = score[q.key]
          return (
            <fieldset key={q.key}>
              <legend className="text-[14px]">
                <span className="font-mincho text-hare">{q.no}・{q.title}</span>
                <span className="pl-2">{q.question}</span>
              </legend>
              <p className="mt-0.5 text-[12px] text-sumi-55">{q.hint}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Array.from({ length: MAX_PER_QUESTION + 1 }, (_, n) => (
                  <label
                    key={n}
                    className={`tabular flex h-9 w-9 cursor-pointer items-center justify-center border text-[14px] ${
                      value === n
                        ? 'border-sumi bg-sumi text-washi'
                        : 'border-line bg-white hover:border-hare'
                    }`}
                  >
                    <input
                      type="radio"
                      name={q.key}
                      value={n}
                      checked={value === n}
                      onChange={() => setScore((prev) => ({ ...prev, [q.key]: n }))}
                      className="sr-only"
                    />
                    {n}
                  </label>
                ))}
              </div>
            </fieldset>
          )
        })}
      </div>

      <div className="mt-6">
        <label htmlFor={`comment-${characterId}`} className="block text-[13px] text-sumi-70">
          コメント
        </label>
        <textarea
          id={`comment-${characterId}`}
          name="comment"
          rows={3}
          defaultValue={initial?.comment ?? ''}
          className="mt-1.5 w-full border border-line px-3 py-2 text-[14px] outline-none focus:border-hare"
        />
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-line pt-4">
        <p className="tabular text-[14px]">
          合計 <span className="font-mincho text-[22px]">{total}</span>
          <span className="text-sumi-55"> / {MAX_TOTAL}</span>
        </p>
        <p className="text-[14px]">
          この一票の判定：
          <span className={isCutOff ? 'text-hare' : ''}>{VERDICT_LABELS[preview]}</span>
          <span className="pl-2 text-[12px] text-sumi-55">{VERDICT_NOTES[preview]}</span>
        </p>
      </div>

      {isCutOff ? (
        <p className="mt-3 border border-hare/40 bg-hare/8 px-3 py-2 text-[13px] text-hare">
          第三問「暦」が0点です。他が満点でも足切りで見送りになります。
        </p>
      ) : null}

      <button
        type="submit"
        className="mt-5 bg-sumi px-5 py-2.5 text-[14px] text-washi transition-opacity hover:opacity-85"
      >
        この採点を保存する
      </button>
    </form>
  )
}
