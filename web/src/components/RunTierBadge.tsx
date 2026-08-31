import { useState } from 'react'
import { t } from '../i18n'

export interface ToolTierEvent {
  tool: string
  tier: 'real' | 'sim' | string
  reason: string
}

export interface RunTierBadgeProps {
  real: number
  sim: number
  items: ToolTierEvent[]
}

const REASONS: Record<string, string> = {
  installed: 'run.tier.reason.installed',
  missing_fallback: 'run.tier.reason.missing_fallback',
  forced_by_binding: 'run.tier.reason.forced_by_binding',
}

function reasonText(reason: string): string {
  const key = REASONS[reason]
  return key ? t(key) : reason
}

/** Run-header badge: "Real N / Sim M" with a per-tool detail popover
 * (task F / T-T3). Hidden until the run executes at least one tool. */
export function RunTierBadge({ real, sim, items }: RunTierBadgeProps) {
  const [open, setOpen] = useState(false)
  if (real + sim === 0) return null
  return (
    <div className="run-tier-wrap">
      <button
        type="button"
        className="run-tier-badge"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        title={t('run.tier.title')}
      >
        <span className="run-tier-real">
          {t('run.tier.real')} {real}
        </span>
        <span className="run-tier-sep">/</span>
        <span className="run-tier-sim">
          {t('run.tier.sim')} {sim}
        </span>
      </button>
      {open && (
        <div className="run-tier-detail">
          {items.length === 0 ? (
            <div className="run-tier-row muted">{t('run.tier.empty')}</div>
          ) : (
            items.map((item, index) => (
              <div key={`${item.tool}-${index}`} className="run-tier-row">
                <span className="run-tier-tool">{item.tool}</span>
                <span className={`run-tier-flag run-tier-flag-${item.tier}`}>
                  {item.tier === 'real' ? t('run.tier.real') : t('run.tier.sim')}
                </span>
                <span className="run-tier-reason">{reasonText(item.reason)}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
