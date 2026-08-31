import { useEffect, useState } from 'react'
import { Crosshair } from '@phosphor-icons/react'
import { getScope, putScope } from '../../api'
import type { ScopePolicy } from '../../types'
import { Button } from '../ui/Button'
import { ChipInput } from './ChipInput'
import { isBlockedScope, validateCidr, validateDomain, validateIp } from '../../lib/scopeValidate'
import { t, useLang } from '../../i18n'

const EMPTY: ScopePolicy = { allow_domains: [], allow_ips: [], allow_cidrs: [], allow_ports: [], allow_url_prefixes: [] }

export function ScopeSection() {
  useLang()
  const [scope, setScope] = useState<ScopePolicy>(EMPTY)
  const [mode, setMode] = useState<'domain' | 'ip'>('domain')
  const [saved, setSaved] = useState('')
  const [warning, setWarning] = useState('')

  useEffect(() => {
    getScope().then((value) =>
      setScope({
        allow_domains: value.allow_domains ?? [],
        allow_ips: value.allow_ips ?? [],
        allow_cidrs: value.allow_cidrs ?? [],
        allow_ports: value.allow_ports ?? [],
        allow_url_prefixes: value.allow_url_prefixes ?? [],
      }),
    )
  }, [])

  async function save() {
    const domains = mode === 'domain' ? scope.allow_domains : []
    const ips = mode === 'ip' ? scope.allow_ips : []
    const cidrs = mode === 'ip' ? scope.allow_cidrs : []
    if (domains.some(isBlockedScope) || ips.some(isBlockedScope) || cidrs.some(isBlockedScope)) {
      setWarning(t('scope.blocked'))
      return
    }
    const next = { ...EMPTY, ...scope, allow_domains: domains, allow_ips: ips, allow_cidrs: cidrs }
    await putScope(next)
    setScope(next)
    setSaved(t('scope.saved'))
    setWarning('')
  }

  return (
    <section className="settings-section card">
      <div className="section-card-head">
        <span className="section-card-icon" aria-hidden>
          <Crosshair size={17} weight="bold" />
        </span>
        <div className="section-card-text">
          <h3 className="section-card-title">{t('scope.title')}</h3>
          <p className="section-card-desc">{t('scope.desc')}</p>
        </div>
      </div>
      <div className="section-card-body">
        <div className="field">
          <span>{t('scope.mode')}</span>
          <div className="provider-grid" role="radiogroup" aria-label={t('scope.mode')}>
            {(['domain', 'ip'] as const).map((m) => (
              <label key={m} className={`provider-option ${mode === m ? 'active' : ''}`}>
                <input type="radio" name="scope-mode" value={m} checked={mode === m} onChange={() => setMode(m)} />
                <span className="provider-option-name">{t(`scope.mode.${m}`)}</span>
              </label>
            ))}
          </div>
        </div>
        {mode === 'domain' && (
          <div className="field">
            <span>{t('scope.domains')}</span>
            <ChipInput value={scope.allow_domains} onChange={(v) => { setScope({ ...scope, allow_domains: v }); setSaved('') }} validate={(v) => validateDomain(v).valid} placeholder="example.com" ariaLabel={t('scope.domains')} />
          </div>
        )}
        {mode === 'ip' && (
          <>
            <div className="field">
              <span>{t('scope.ips')}</span>
              <ChipInput value={scope.allow_ips} onChange={(v) => { setScope({ ...scope, allow_ips: v }); setSaved('') }} validate={(v) => validateIp(v).valid} placeholder="203.0.113.10" ariaLabel={t('scope.ips')} />
            </div>
            <div className="field">
              <span>{t('scope.cidrs')}</span>
              <ChipInput value={scope.allow_cidrs} onChange={(v) => { setScope({ ...scope, allow_cidrs: v }); setSaved('') }} validate={(v) => validateCidr(v).valid} placeholder="203.0.113.0/24" ariaLabel={t('scope.cidrs')} />
            </div>
          </>
        )}
        <div className="field">
          <span>{t('scope.ports')}</span>
          <input className="input" value={scope.allow_ports.join(', ')} onChange={(e) => { setScope({ ...scope, allow_ports: e.target.value.split(',').map((v) => Number(v.trim())).filter(Number.isFinite) }); setSaved('') }} placeholder="80, 443, 8080" />
        </div>
        <div className="field field--wide">
          <span>{t('scope.urlPrefixes')}</span>
          <textarea className="textarea" value={scope.allow_url_prefixes.join('\n')} onChange={(e) => { setScope({ ...scope, allow_url_prefixes: e.target.value.split('\n').map((v) => v.trim()).filter(Boolean) }); setSaved('') }} placeholder="https://example.com/api/" />
        </div>
        <div className="toolbar">
          <div className="toolbar-spacer" />
          {warning && <span className="settings-result fail">{warning}</span>}
          {saved && <span className="settings-result success">{saved}</span>}
          <Button variant="primary" onClick={save}>{t('scope.save')}</Button>
        </div>
      </div>
    </section>
  )
}
