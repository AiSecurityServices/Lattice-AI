import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

export interface SegmentedOption<T extends string> {
  value: T
  label: string
  icon?: ReactNode
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}: {
  options: Array<SegmentedOption<T>>
  value: T
  onChange: (value: T) => void
  ariaLabel?: string
  className?: string
}) {
  return (
    <div className={cn('segmented', className)} role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={cn('segmented-item', value === option.value && 'active')}
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.icon && (
            <span className="segmented-icon" aria-hidden>
              {option.icon}
            </span>
          )}
          <span>{option.label}</span>
        </button>
      ))}
    </div>
  )
}
