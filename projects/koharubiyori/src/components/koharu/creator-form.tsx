import { STATUS_LABELS } from '@/lib/koharu/constants'
import type { Creator } from '@/lib/koharu/queries'
import type { Enums } from '@/types/database'

const STATUSES: Enums<'publish_status'>[] = ['draft', 'published', 'archived']

function Field({
  name,
  label,
  hint,
  defaultValue,
  type = 'text',
  required = false,
}: {
  name: string
  label: string
  hint?: string
  defaultValue?: string | null
  type?: string
  required?: boolean
}) {
  return (
    <div>
      <label htmlFor={name} className="block text-[13px] text-sumi-70">
        {label}
        {required ? <span className="pl-1 text-hare">*</span> : null}
      </label>
      {hint ? <p className="mt-0.5 text-[12px] text-sumi-55">{hint}</p> : null}
      <input
        id={name}
        name={name}
        type={type}
        required={required}
        defaultValue={defaultValue ?? ''}
        className="mt-1.5 w-full border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
      />
    </div>
  )
}

function TextArea({
  name,
  label,
  hint,
  rows = 4,
  defaultValue,
}: {
  name: string
  label: string
  hint?: string
  rows?: number
  defaultValue?: string | null
}) {
  return (
    <div>
      <label htmlFor={name} className="block text-[13px] text-sumi-70">
        {label}
      </label>
      {hint ? <p className="mt-0.5 text-[12px] text-sumi-55">{hint}</p> : null}
      <textarea
        id={name}
        name={name}
        rows={rows}
        defaultValue={defaultValue ?? ''}
        className="mt-1.5 w-full border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
      />
    </div>
  )
}

export function CreatorForm({
  action,
  creator,
  submitLabel,
}: {
  action: (formData: FormData) => void
  creator?: Creator
  submitLabel: string
}) {
  return (
    <form action={action} className="space-y-6">
      {creator ? <input type="hidden" name="id" value={creator.id} /> : null}

      <div className="grid gap-6 sm:grid-cols-2">
        <Field name="name" label="作家名" required defaultValue={creator?.name} />
        <Field name="name_kana" label="よみ" defaultValue={creator?.name_kana} />
        <Field
          name="slug"
          label="スラッグ"
          hint="/sakka/[slug] になる。英小文字・数字・ハイフンのみ"
          required
          defaultValue={creator?.slug}
        />
        <Field
          name="title"
          label="肩書"
          hint="例：絵の描き手／革の作り手"
          defaultValue={creator?.title}
        />
        <Field name="base_area" label="拠点" hint="例：京都・伏見" defaultValue={creator?.base_area} />
        <Field
          name="first_engaged_on"
          label="初回起用日"
          type="date"
          defaultValue={creator?.first_engaged_on}
        />
      </div>

      <TextArea
        name="profile"
        label="プロフィール"
        hint="200〜400字。運営が書く。作家の自己紹介文をそのまま載せない"
        rows={6}
        defaultValue={creator?.profile}
      />
      <TextArea
        name="tsukumo_note"
        label="ツクモの一言"
        hint="編集長ツクモによる紹介文。1〜2行"
        rows={2}
        defaultValue={creator?.tsukumo_note}
      />

      <div className="grid gap-6 sm:grid-cols-2">
        <Field
          name="hero_image_url"
          label="主画像URL"
          hint="代表作か掛け紙原画。作家ページで最も大きく出る"
          defaultValue={creator?.hero_image_url}
        />
        <Field name="photo_url" label="顔写真URL" defaultValue={creator?.photo_url} />
        <Field
          name="ec_url"
          label="作家自身のEC"
          hint="送客先。参画メリットの実体"
          defaultValue={creator?.ec_url}
        />
        <Field name="website_url" label="ウェブサイト" defaultValue={creator?.website_url} />
        <Field name="sns_instagram" label="Instagram" defaultValue={creator?.sns_instagram} />
        <Field name="sns_x" label="X" defaultValue={creator?.sns_x} />
      </div>

      <TextArea
        name="notes"
        label="社内メモ"
        hint="非公開。判定の確定ログもここに追記される"
        rows={4}
        defaultValue={creator?.notes}
      />

      <div>
        <label htmlFor="status" className="block text-[13px] text-sumi-70">
          公開状態
        </label>
        <p className="mt-0.5 text-[12px] text-sumi-55">
          公開にすると /sakka/[slug] が見えるようになる。それ以外は404
        </p>
        <select
          id="status"
          name="status"
          defaultValue={creator?.status ?? 'draft'}
          className="mt-1.5 border border-line bg-white px-3 py-2 text-[14px] outline-none focus:border-hare"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
      </div>

      <button
        type="submit"
        className="bg-sumi px-6 py-3 text-[14px] text-washi transition-opacity hover:opacity-85"
      >
        {submitLabel}
      </button>
    </form>
  )
}
