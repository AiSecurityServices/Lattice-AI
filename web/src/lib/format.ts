/** Shared time formatting: compact local times instead of raw ISO strings. */
import { t } from '../i18n'

function toDate(iso?: string | null): Date | null {
  if (!iso) return null
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date
}

const pad = (n: number) => String(n).padStart(2, '0')

/** `21:52` today, `08-31 21:52` this year, `2025-08-31` otherwise. */
export function formatTime(iso?: string | null): string {
  const date = toDate(iso)
  if (!date) return iso ? iso.slice(0, 16).replace('T', ' ') : '—'
  const now = new Date()
  const hm = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  const md = `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  if (date.getFullYear() !== now.getFullYear()) return `${date.getFullYear()}-${md}`
  return date.toDateString() === now.toDateString() ? hm : `${md} ${hm}`
}

/** Relative label for the recent past: `刚刚` / `3 分钟前` / `2 小时前` / `5 天前`. */
export function formatRelative(iso?: string | null): string {
  const date = toDate(iso)
  if (!date) return '—'
  const diff = Date.now() - date.getTime()
  const minute = 60_000
  if (diff < minute) return t('fmt.rel.now')
  if (diff < 60 * minute) return t('fmt.rel.min').replace('{n}', String(Math.floor(diff / minute)))
  if (diff < 24 * 60 * minute) return t('fmt.rel.hour').replace('{n}', String(Math.floor(diff / (60 * minute))))
  if (diff < 7 * 24 * 60 * minute) return t('fmt.rel.day').replace('{n}', String(Math.floor(diff / (24 * 60 * minute))))
  return formatTime(iso)
}

/** Timestamp suffix for default names: `任务 21:52` stays unique and scannable. */
export function timeSuffix(date = new Date()): string {
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}
