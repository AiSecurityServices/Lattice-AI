import { useEffect, useRef, useState } from 'react'
import { t } from '../../i18n'
import { Button } from './Button'

export function NameDialog({
  open,
  title,
  initialValue = '',
  // default evaluated at render time so it follows the current language
  confirmLabel = t('cd.confirm'),
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  initialValue?: string
  confirmLabel?: string
  onConfirm: (value: string) => void
  onCancel: () => void
}) {
  const [value, setValue] = useState(initialValue)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setValue(initialValue)
      inputRef.current?.focus()
    }
  }, [open, initialValue])

  if (!open) return null

  function submit() {
    if (!value.trim()) return
    onConfirm(value.trim())
  }

  return (
    <div className="dialog-backdrop" onMouseDown={onCancel}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <h3>{title}</h3>
        <label className="field">
          <span>{t('nd.name')}</span>
          <input
            ref={inputRef}
            className="input"
            autoFocus
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') submit()
              if (event.key === 'Escape') onCancel()
            }}
          />
        </label>
        <div className="dialog-actions">
          <Button onClick={onCancel}>{t('common.cancel')}</Button>
          <Button variant="primary" disabled={!value.trim()} onClick={submit}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
