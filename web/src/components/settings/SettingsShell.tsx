import { useState } from 'react'
import { MagnifyingGlass } from '@phosphor-icons/react'
import { SETTINGS_GROUPS, SETTINGS_SECTIONS } from '../../settingsections'
import { useHashSection } from '../../hooks/useHashSection'
import { t, useLang } from '../../i18n'
import { GeneralSection } from './GeneralSection'
import { LlmSection } from './LlmSection'
import { PolicySection } from './PolicySection'
import { ScopeSection } from './ScopeSection'
import { ToolchainSection } from './ToolchainSection'

export function SettingsShell() {
  useLang()
  const [section, navigate] = useHashSection('llm')
  const [query, setQuery] = useState('')
  const labelFor = (s: (typeof SETTINGS_SECTIONS)[number]) => t(`nav.${s.id}`)
  const sections = SETTINGS_SECTIONS.filter((s) => labelFor(s).toLowerCase().includes(query.toLowerCase()))

  return (
    <div className="settings-shell">
      <aside className="settings-nav">
        <div className="settings-search">
          <MagnifyingGlass size={14} />
          <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('shell.search')} aria-label={t('shell.search')} />
        </div>
        {SETTINGS_GROUPS.map((g) => {
          const items = sections.filter((s) => s.group === g.key)
          if (!items.length) return null
          return (
            <div className="settings-nav-group" key={g.key}>
              <div className="settings-nav-group-label">{t(`nav.group.${g.key}`)}</div>
              {items.map((s) => (
                <button key={s.id} className={`settings-nav-item ${section === s.id ? 'active' : ''}`} onClick={() => navigate(s.id)}>
                  <span className="settings-nav-icon" aria-hidden>
                    {s.icon}
                  </span>
                  {labelFor(s)}
                </button>
              ))}
            </div>
          )
        })}
      </aside>
      <div className="settings-panel">
        {section === 'llm' && <LlmSection />}
        {section === 'scope' && <ScopeSection />}
        {section === 'plan' && <PolicySection />}
        {section === 'toolchain' && <ToolchainSection />}
        {section === 'general' && <GeneralSection />}
      </div>
    </div>
  )
}
