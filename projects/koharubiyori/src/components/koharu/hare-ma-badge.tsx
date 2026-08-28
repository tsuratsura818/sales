import { HARE_MA_LABELS } from '@/lib/koharu/constants'
import type { Enums } from '@/types/database'

export function HareMaBadge({ hareMa }: { hareMa: Enums<'hare_ma'> }) {
  return (
    <span className="inline-flex items-center rounded-full border border-hare/40 bg-hare/8 px-3 py-1 text-[13px] leading-none text-hare">
      {HARE_MA_LABELS[hareMa]}
    </span>
  )
}
