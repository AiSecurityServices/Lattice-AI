import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/cn'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
  size?: 'sm' | 'md'
  loading?: boolean
  icon?: ReactNode
  iconRight?: ReactNode
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  disabled,
  icon,
  iconRight,
  className,
  children,
  ...props
}: ButtonProps) {
  const variantClass = {
    primary: 'btn-primary',
    secondary: '',
    danger: 'btn-danger',
    ghost: 'btn-ghost',
  }[variant]

  return (
    <button
      className={cn('btn', variantClass, size === 'sm' && 'btn-sm', className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? (
        <span className="btn-spinner" aria-hidden />
      ) : (
        icon && (
          <span className="btn-icon" aria-hidden>
            {icon}
          </span>
        )
      )}
      <span className="btn-label">{children}</span>
      {iconRight && !loading && (
        <span className="btn-icon" aria-hidden>
          {iconRight}
        </span>
      )}
    </button>
  )
}
