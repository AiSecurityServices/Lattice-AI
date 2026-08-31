import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

export function Field({
  label,
  hint,
  error,
  className,
  children,
}: {
  label: string
  hint?: string
  error?: string
  className?: string
  children: ReactNode
}) {
  return (
    <label className={cn('field', className)}>
      <span>{label}</span>
      {children}
      {hint && <span className="muted">{hint}</span>}
      {error && <span className="field-error">{error}</span>}
    </label>
  )
}
