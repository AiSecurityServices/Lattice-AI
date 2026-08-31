import { useEffect, useRef } from 'react'
import { Warning } from '@phosphor-icons/react'
import { t } from '../../i18n'
import { Button } from './Button'

export function ConfirmDialog({
  open,
  title,
  description,
  // default evaluated at render time so it follows the current language
  confirmLabel = t('cd.confirm'),
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  description?: string
  confirmLabel?: string
  danger?: boolean
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    dialogRef.current?.focus()
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div className="dialog-backdrop" onMouseDown={onCancel}>
      <div
        ref={dialogRef}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <h3 className="dialog-title">
          {danger && (
            <span className="dialog-title-icon" aria-hidden>
              <Warning size={18} weight="fill" />
            </span>
          )}
          {title}
        </h3>
        {description && <p>{description}</p>}
        <div className="dialog-actions">
          <Button onClick={onCancel} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} loading={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
