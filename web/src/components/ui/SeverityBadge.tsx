import type { ReactNode } from 'react'
import { t, useLang } from '../../i18n'
import { cn } from '../../lib/cn'

// Unified severity palette (soft-badge family): tokens live in index.css
// under --sev-*; used by FindingsPage, RunReport and the dashboard feed.
const SEVERITY_KEYS: readonly string[] = ['critical', 'high', 'medium', 'low', 'info']

export function severityKey(value: string): string {
  return SEVERITY_KEYS.includes(value) ? value : 'info'
}

export function SeverityBadge({ severity, children }: { severity: string; children?: ReactNode }) {
  useLang()
  const key = severityKey(severity)
  return <span className={cn('sev-badge', `sev-${key}`)}>{children ?? t(`sev.${key}`)}</span>
}
