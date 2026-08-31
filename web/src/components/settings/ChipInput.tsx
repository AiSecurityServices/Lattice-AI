import { useState } from 'react'
import { X } from '@phosphor-icons/react'
import { t } from '../../i18n'

export function ChipInput({
  value,
  onChange,
  parse,
  validate,
  placeholder,
  ariaLabel,
}: {
  value: string[]
  onChange: (next: string[]) => void
  parse?: (raw: string) => string[]
  validate?: (item: string) => boolean
  placeholder?: string
  ariaLabel?: string
}) {
  const [draft, setDraft] = useState('')

  function commit() {
    const raw = draft.trim()
    if (!raw) return
    const items = parse ? parse(raw) : raw.split(',')
    const existing = new Set(value)
    const merged = [...value]
    for (const item of items) {
      const t = item.trim()
      if (!t || existing.has(t)) continue
      if (validate && !validate(t)) continue
      existing.add(t)
      merged.push(t)
    }
    onChange(merged)
    setDraft('')
  }

  return (
    <div className="chip-input">
      <div className="chip-list">
        {value.map((item) => (
          <span key={item} className="chip">
            {item}
            <button type="button" aria-label={t('chip.remove').replace('{name}', item)} onClick={() => onChange(value.filter((v) => v !== item))}>
              <X size={10} weight="bold" />
            </button>
          </span>
        ))}
        <input
          className="chip-draft input"
          value={draft}
          placeholder={placeholder}
          aria-label={ariaLabel ?? placeholder ?? t('chip.input')}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault()
              commit()
            }
          }}
          onBlur={commit}
        />
      </div>
    </div>
  )
}
