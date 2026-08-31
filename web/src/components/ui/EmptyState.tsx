import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

export function EmptyState({
  title,
  description,
  action,
  icon,
  className,
}: {
  title: string
  description?: string
  action?: ReactNode
  icon?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('empty', className)} role="status">
      {icon && (
        <div className="empty-icon" aria-hidden>
          {icon}
        </div>
      )}
      <div className="empty-title">{title}</div>
      {description && <div className="empty-desc">{description}</div>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  )
}
