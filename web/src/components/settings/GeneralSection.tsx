import { useEffect, useState, type ReactNode } from 'react'
import { GearSix, Monitor, Moon, Sun } from '@phosphor-icons/react'
import { getPreferences, putPreferences } from '../../api'
import type { Preferences } from '../../types'
import { setLang, t, useLang } from '../../i18n'
import { applyTheme, type ThemePref } from '../../theme'

const THEMES: Array<{ value: ThemePref; label: string; icon: ReactNode; preview: string }> = [
  { value: 'system', label: 'general.theme.system', icon: <Monitor size={14} weight="bold" />, preview: 'system' },
  { value: 'light', label: 'general.theme.light', icon: <Sun size={14} weight="bold" />, preview: 'light' },
  { value: 'dark', label: 'general.theme.dark', icon: <Moon size={14} weight="bold" />, preview: 'dark' },
]
const LANGS: Preferences['language'][] = ['zh', 'en']

export function GeneralSection() {
  useLang()
  const [prefs, setPrefs] = useState<Preferences>({ theme: 'system', language: 'zh' })
  const [saved, setSaved] = useState('')

  useEffect(() => {
    getPreferences()
      .then((p) => {
        setPrefs({ theme: p.theme, language: p.language })
        applyTheme(p.theme)
      })
      .catch(() => {})
  }, [])

  async function changeTheme(theme: ThemePref) {
    setPrefs((prev) => ({ ...prev, theme }))
    applyTheme(theme)
    await putPreferences({ theme })
    setSaved(t('general.saved'))
  }

  async function changeLang(language: Preferences['language']) {
    setPrefs((prev) => ({ ...prev, language }))
    setLang(language)
    await putPreferences({ language })
    setSaved(t('general.saved'))
  }

  return (
    <section className="settings-section card">
      <div className="section-card-head">
        <span className="section-card-icon" aria-hidden>
          <GearSix size={17} weight="bold" />
        </span>
        <div className="section-card-text">
          <h3 className="section-card-title">{t('general.title')}</h3>
          <p className="section-card-desc">{t('general.desc')}</p>
        </div>
      </div>
      <div className="section-card-body">
        <div className="field">
          <span className="field-label">{t('general.theme')}</span>
          <div className="theme-grid" role="radiogroup" aria-label={t('general.theme')}>
            {THEMES.map((th) => (
              <label key={th.value} className={`theme-option ${prefs.theme === th.value ? 'active' : ''}`}>
                <input
                  type="radio"
                  name="pref-theme"
                  value={th.value}
                  checked={prefs.theme === th.value}
                  onChange={(e) => void changeTheme(e.target.value as ThemePref)}
                />
                <span className="theme-option-name">
                  <span aria-hidden>{th.icon}</span>
                  {t(th.label)}
                </span>
                <span className={`theme-preview ${th.preview}`} aria-hidden>
                  <span className="pv-side" />
                  <span className="pv-panel">
                    <span className="pv-line wide" />
                    <span className="pv-line short" />
                    <span className="pv-line" />
                  </span>
                </span>
              </label>
            ))}
          </div>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="pref-lang">{t('general.language')}</label>
          <select className="select" id="pref-lang" aria-label={t('general.language')} value={prefs.language} onChange={(e) => void changeLang(e.target.value as Preferences['language'])}>
            {LANGS.map((l) => <option key={l} value={l}>{l === 'zh' ? t('general.lang.zh') : t('general.lang.en')}</option>)}
          </select>
        </div>
        {saved && <span className="settings-result success">{saved}</span>}
      </div>
    </section>
  )
}
