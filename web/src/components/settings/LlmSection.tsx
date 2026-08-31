import { useEffect, useState } from 'react'
import { ArrowClockwise, Eye, EyeSlash, Plugs } from '@phosphor-icons/react'
import { getSettings, listModels, listProviders, putSettings, testProvider } from '../../api'
import type { ProviderMeta, Settings } from '../../types'
import { Button } from '../ui/Button'
import { t, useLang } from '../../i18n'

const CUSTOM = '__custom__'

export function LlmSection() {
  useLang()
  const [s, setS] = useState<Settings | null>(null)
  const [presets, setPresets] = useState<Record<string, ProviderMeta>>({})
  const [models, setModels] = useState<string[]>([])
  const [efforts, setEfforts] = useState<string[]>([])
  const [fetching, setFetching] = useState(false)
  const [saved, setSaved] = useState('')
  const [testing, setTesting] = useState(false)
  const [showKey, setShowKey] = useState(false)

  useEffect(() => {
    getSettings().then((settings) => {
      setS(settings)
      refreshModels(settings.base_url, settings.api_key)
    })
    listProviders().then((r) => setPresets(r.providers)).catch(() => setPresets({}))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const isCustom = !!s && (!presets[s.provider] || s.provider === CUSTOM)
  const providerOptions = [
    ...Object.entries(presets).map(([key, meta]) => ({ key, name: meta.name, model: meta.model })),
    { key: CUSTOM, name: t('llm.custom'), model: t('llm.custom.desc') },
  ]

  function selectProvider(key: string) {
    if (!s) return
    setSaved('')
    if (key === CUSTOM) {
      setS({ ...s, provider: CUSTOM })
      return
    }
    const preset = presets[key]
    if (!preset) return
    setS({ ...s, provider: key, base_url: preset.base_url, model: preset.model })
    refreshModels(preset.base_url, s.api_key)
  }

  async function refreshModels(base_url: string, api_key: string) {
    if (!base_url.trim()) {
      setModels([])
      setEfforts([])
      return
    }
    setFetching(true)
    setSaved('')
    try {
      const r = await listModels({ base_url: base_url.trim(), api_key: api_key.trim() })
      setModels(r.models)
      setEfforts(r.efforts ?? [])
    } catch {
      setModels([])
      setEfforts([])
    } finally {
      setFetching(false)
    }
  }

  async function test() {
    if (!s) return
    setTesting(true)
    setSaved('')
    try {
      await testProvider({ base_url: s.base_url, api_key: s.api_key, model: s.model })
    } catch {
      setSaved(t('llm.testFail'))
    } finally {
      setTesting(false)
    }
  }

  async function save() {
    if (!s) return
    setS(await putSettings(s))
    setSaved(t('llm.saved'))
  }

  if (!s) return <p className="muted">{t('llm.loading')}</p>

  return (
    <section className="settings-section card">
      <div className="section-card-head">
        <span className="section-card-icon" aria-hidden>
          <Plugs size={17} weight="bold" />
        </span>
        <div className="section-card-text">
          <h3 className="section-card-title">{t('llm.title')}</h3>
          <p className="section-card-desc">{t('llm.desc')}</p>
        </div>
      </div>
      <div className="section-card-body">
        <div className="field">
          <span>{t('llm.provider')}</span>
          <div className="provider-grid" role="radiogroup" aria-label={t('llm.provider')}>
            {providerOptions.map((opt) => (
              <label key={opt.key} className={`provider-option ${s.provider === opt.key ? 'active' : ''}`}>
                <input type="radio" name="provider" value={opt.key} checked={s.provider === opt.key} onChange={() => selectProvider(opt.key)} />
                <span>
                  <span className="provider-option-name">{opt.name}</span>
                  <br />
                  <span className="provider-option-model">{opt.model}</span>
                </span>
              </label>
            ))}
          </div>
          {isCustom && <p className="muted">{t('llm.custom.desc')}</p>}
        </div>

        <div className="field">
          <span>{t('llm.baseUrl')}</span>
          <input className="input" value={s.base_url} onChange={(e) => { setS({ ...s, base_url: e.target.value }); setSaved('') }} placeholder="https://api.example.com/v1" aria-label={t('llm.baseUrl')} />
        </div>
        <div className="field">
          <span>{t('llm.model')}</span>
          <div className="inline-flex">
            <input className="input" list="llm-model-options" value={s.model} onChange={(e) => { setS({ ...s, model: e.target.value }); setSaved('') }} placeholder="model-id" aria-label={t('llm.model')} />
            <datalist id="llm-model-options">
              {models.map((m) => <option key={m} value={m} />)}
            </datalist>
            <Button size="sm" variant="secondary" icon={<ArrowClockwise size={15} weight="bold" />} loading={fetching} onClick={() => refreshModels(s.base_url, s.api_key)}>
              {t('llm.fetchModels')}
            </Button>
          </div>
        </div>
        {(efforts.length > 0 || s.reasoning_effort) && (
          <div className="field">
            <span>{t('llm.effort')}</span>
            <select className="select" aria-label={t('llm.effort')} value={s.reasoning_effort ?? ''} onChange={(e) => { setS({ ...s, reasoning_effort: e.target.value }); setSaved('') }}>
              <option value="">{t('llm.effort.default')}</option>
              {s.reasoning_effort && !efforts.includes(s.reasoning_effort) && <option value={s.reasoning_effort}>{s.reasoning_effort}</option>}
              {efforts.map((e) => <option key={e} value={e}>{e}</option>)}
            </select>
          </div>
        )}
        <div className="field">
          <span>{t('llm.apiKey')}</span>
          <div className="inline-flex">
            <input className="input" type={showKey ? 'text' : 'password'} value={s.api_key} onChange={(e) => { setS({ ...s, api_key: e.target.value }); setSaved('') }} placeholder={s.has_api_key ? t('llm.keyConfigured') : t('llm.keyPlaceholder')} aria-label={t('llm.apiKey')} />
            <Button size="sm" variant="ghost" aria-label={showKey ? t('llm.hide') : t('llm.show')} icon={showKey ? <EyeSlash size={15} weight="bold" /> : <Eye size={15} weight="bold" />} onClick={() => setShowKey((v) => !v)}>
              {showKey ? t('llm.hide') : t('llm.show')}
            </Button>
          </div>
        </div>
        <div className="toolbar">
          <div className="toolbar-spacer" />
          {saved && <span className="settings-result success">{saved}</span>}
          <Button variant="secondary" icon={<Plugs size={15} weight="bold" />} loading={testing} onClick={test}>
            {testing ? t('llm.testing') : t('llm.test')}
          </Button>
          <Button variant="primary" onClick={save}>{t('llm.save')}</Button>
        </div>
      </div>
    </section>
  )
}
