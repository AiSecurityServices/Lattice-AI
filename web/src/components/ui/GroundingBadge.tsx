import { CheckCircle, Question, Warning } from '@phosphor-icons/react'
import { t, useLang } from '../../i18n'
import { cn } from '../../lib/cn'

export type GroundingStatus = 'verified' | 'unverified' | 'missing_evidence'

const ICONS: Record<GroundingStatus, typeof CheckCircle> = {
  verified: CheckCircle,
  unverified: Question,
  missing_evidence: Warning,
}

/**
 * Evidence-grounding verdict badge (M3-B): green ✓ verified / amber ?
 * unverified / red ⚠ missing_evidence. Soft-badge styling mirrors
 * SeverityBadge; renders nothing when the finding carries no grounding
 * verdict (grounding_policy=off or legacy data).
 */
export function GroundingBadge({
  status,
  children,
}: {
  status?: string | null
  children?: React.ReactNode
}) {
  useLang()
  if (status !== 'verified' && status !== 'unverified' && status !== 'missing_evidence') {
    return null
  }
  const Icon = ICONS[status]
  return (
    <span className={cn('gnd-badge', `gnd-${status}`)} title={t(`gnd.status.${status}`)}>
      <Icon size={12} weight="bold" aria-hidden />
      {children ?? t(`gnd.status.${status}`)}
    </span>
  )
}
