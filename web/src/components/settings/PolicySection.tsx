import { useEffect, useState } from 'react'
import { ShieldWarning } from '@phosphor-icons/react'
import { getSecuritySettings, putSecuritySettings } from '../../api'
import type { DangerPolicy } from '../../types'
import { Button } from '../ui/Button'
import { t, useLang } from '../../i18n'

const LEVELS: DangerPolicy['level'][] = ['strict', 'standard', 'lenient']

export function PolicySection() {
  useLang()
  const [danger, setDanger] = useState<DangerPolicy>({ level: 'standard', whitelist: [] })
  const [pending, setPending] = useState<DangerPolicy['level'] | null>(null)
  const [saved, setSaved] = useState('')

  useEffect(() => {
    getSecuritySettings().then((value) => setDanger({ level: value.level ?? 'standard', whitelist: value.whitelist ?? [] }))
  }, [])

  async function save(level: DangerPolicy['level']) {
    const next = { ...danger, level }
    await putSecuritySettings(next)
    setDanger(next)
    setSaved(t('policy.saved'))
  }

  function choose(level: DangerPolicy['level']) {
    setSaved('')
    if (level === 'lenient' && danger.level !== 'lenient') {
      setPending(level)
      return
    }
    void save(level)
  }

  return (
    <section className="settings-section card">
      <div className="section-card-head">
        <span className="section-card-icon" aria-hidden>
          <ShieldWarning size={17} weight="bold" />
        </span>
        <div className="section-card-text">
          <h3 className="section-card-title">{t('policy.title')}</h3>
          <p className="section-card-desc">{t('policy.desc')}</p>
        </div>
      </div>
      <div className="section-card-body">
        <div className="provider-grid" role="radiogroup" aria-label={t('policy.title')}>
          {LEVELS.map((level) => (
            <label key={level} className={`danger-option ${danger.level === level ? 'active' : ''}`}>
              <input type="radio" name="danger-level" value={level} checked={danger.level === level} onChange={() => choose(level)} />
              <span className="danger-option-name">{t(`policy.${level}`)}</span>
              <span className="danger-option-desc">{t(`policy.${level}.desc`)}</span>
            </label>
          ))}
        </div>
        <div className="toolbar">
          <div className="toolbar-spacer" />
          {saved && <span className="settings-result success">{saved}</span>}
          <Button variant="primary" onClick={() => void save(danger.level)}>{t('policy.save')}</Button>
        </div>
      </div>
      {pending === 'lenient' && (
        <div className="confirm-dialog" role="dialog" aria-label={t('policy.confirm.title')}>
          <p>{t('policy.confirm.body')}</p>
          <div className="confirm-actions">
            <Button variant="ghost" onClick={() => setPending(null)}>{t('policy.confirm.cancel')}</Button>
            <Button variant="danger" onClick={() => { void save('lenient'); setPending(null) }}>{t('policy.confirm.ok')}</Button>
          </div>
        </div>
      )}
    </section>
  )
}
