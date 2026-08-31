import { useState } from 'react'
import { t, useLang } from '../i18n'
import { ReadOnlySummary } from './ui/ReadOnlySummary'
import type { Tool } from '../types'

interface Props {
  tool: Tool
  onSave: (tool: Tool) => void
  onCancel: () => void
  onTest: (tool: Tool, args: Record<string, unknown>) => Promise<unknown>
}

type ParamProperty = {
  type?: string
  title?: string
  description?: string
  default?: unknown
}

type ParameterSchema = {
  type?: string
  properties?: Record<string, ParamProperty>
  required?: string[]
}

const TARGET_TYPES = ['web', 'network', 'host', 'service'] as const

export default function ToolEditor({ tool, onSave, onCancel, onTest }: Props) {
  useLang()
  const [draft, setDraft] = useState<Tool>({ ...tool })
  const [testArgs, setTestArgs] = useState<Record<string, unknown>>({})
  const [testResult, setTestResult] = useState('')
  const [testError, setTestError] = useState('')
  const [running, setRunning] = useState(false)

  const parameterSchema = (() => {
    const parameters = draft.parameters as ParameterSchema | undefined
    if (!parameters || parameters.type !== 'object' || !parameters.properties) return null
    return parameters
  })()
  const parameterEntries = Object.entries(parameterSchema?.properties ?? {})

  function patch(field: keyof Tool, value: unknown) {
    setDraft((d) => ({ ...d, [field]: value } as Tool))
  }

  function updateTestArg(key: string, value: unknown) {
    setTestArgs((prev) => ({ ...prev, [key]: value }))
  }

  async function runTest() {
    setTestError('')
    setTestResult('')
    setRunning(true)
    try {
      const args: Record<string, unknown> = { ...testArgs }
      if (parameterEntries.length > 0) {
        for (const [key, prop] of parameterEntries) {
          const value = args[key]
          if (prop.type === 'number') {
            if (value === '' || value == null) {
              delete args[key]
            } else {
              args[key] = Number(value)
            }
          } else if (prop.type === 'boolean') {
            args[key] = Boolean(value)
          } else if (prop.type === 'array' || prop.type === 'object') {
            if (typeof value === 'string' && value.trim()) {
              try {
                args[key] = JSON.parse(value)
              } catch {
                setTestError(t('ted.invalidJson').replace('{name}', key))
                return
              }
            }
          }
        }
      }
      const result = await onTest(draft, args)
      setTestResult(JSON.stringify(result, null, 2))
    } catch (e) {
      setTestError(String(e))
    } finally {
      setRunning(false)
    }
  }

  function renderTestInput(key: string, prop: ParamProperty) {
    const label = prop.title || key
    const required = parameterSchema?.required?.includes(key) ?? false
    const value = testArgs[key] ?? prop.default ?? ''

    if (prop.type === 'boolean') {
      return (
        <label key={key} className="field" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input type="checkbox" checked={Boolean(value)} onChange={(e) => updateTestArg(key, e.target.checked)} />
          <span>{label}{required ? ' *' : ''}</span>
        </label>
      )
    }

    if (prop.type === 'number') {
      return (
        <div key={key} className="field">
          <span>{label}{required ? ' *' : ''}</span>
          <input
            className="input"
            type="number"
            value={String(value ?? '')}
            onChange={(e) => updateTestArg(key, e.target.value === '' ? '' : Number(e.target.value))}
          />
        </div>
      )
    }

    if (prop.type === 'array' || prop.type === 'object') {
      return (
        <div key={key} className="field">
          <span>{label}{required ? ' *' : ''}</span>
          <textarea
            className="textarea"
            rows={3}
            value={typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
            onChange={(e) => updateTestArg(key, e.target.value)}
            style={{ fontFamily: 'monospace', fontSize: 12 }}
          />
        </div>
      )
    }

    return (
      <div key={key} className="field">
        <span>{label}{required ? ' *' : ''}</span>
        <input
          className="input"
          value={String(value ?? '')}
          onChange={(e) => updateTestArg(key, e.target.value)}
          placeholder={prop.description || label}
        />
      </div>
    )
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h4 style={{ margin: '0 0 12px' }}>{t('ted.title')}</h4>
      <div className="field">
        <span>{t('nd.name')}</span>
        <input className="input" value={draft.name} onChange={(e) => patch('name', e.target.value)} />
      </div>
      <div className="field">
        <span>{t('ted.description')}</span>
        <input className="input" value={draft.description ?? ''} onChange={(e) => patch('description', e.target.value)} />
      </div>
      <div className="field">
        <span>{t('ted.type')}</span>
        <select className="select" value={draft.runner ?? 'cli'} onChange={(e) => patch('runner', e.target.value)}>
          <option value="cli">cli</option>
          <option value="builtin">builtin</option>
        </select>
      </div>
      <div className="field">
        <ReadOnlySummary title={t('ted.command')} value={draft.command ?? []} />
      </div>
      <div className="field">
        <ReadOnlySummary title={t('imp.preview.parameters')} value={draft.parameters ?? {}} />
      </div>
      <div className="field">
        <ReadOnlySummary title={t('imp.preview.output')} value={draft.output ?? {}} />
      </div>
      <div className="field">
        <span>{t('imp.preview.approval')}</span>
        <select className="select" value={draft.approval ?? 'allow'} onChange={(e) => patch('approval', e.target.value)}>
          <option value="allow">allow</option>
          <option value="ask">ask</option>
          <option value="deny">deny</option>
        </select>
      </div>
      <div className="field">
        <ReadOnlySummary title="secret_fields" value={draft.secret_fields ?? []} />
      </div>
      <div className="field">
        <span>{t('ted.scopeLabel')}</span>
        <div style={{ display: 'flex', gap: 8 }}>
          {TARGET_TYPES.map((type) => (
            <label key={type}>
              <input
                type="checkbox"
                checked={(draft.scope ?? []).includes(type)}
                onChange={(e) => {
                  const scope = new Set(draft.scope ?? [])
                  if (e.target.checked) scope.add(type)
                  else scope.delete(type)
                  patch('scope', Array.from(scope))
                }}
              />
              {type}
            </label>
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn btn-primary" onClick={() => onSave(draft)}>
          {t('common.save')}
        </button>
        <button className="btn" onClick={onCancel}>
          {t('common.cancel')}
        </button>
      </div>
      <div style={{ borderTop: '1px solid var(--border)', marginTop: 12, paddingTop: 12 }}>
        <div className="muted" style={{ marginBottom: 6 }}>
          {t('ted.testHint')}
        </div>
        {parameterEntries.length === 0 ? (
          <div className="field">
            <span>target *</span>
            <input
              className="input"
              value={String(testArgs.target ?? '')}
              onChange={(e) => updateTestArg('target', e.target.value)}
              placeholder="example.com"
            />
          </div>
        ) : (
          parameterEntries.map(([key, prop]) => renderTestInput(key, prop))
        )}
        <button className="btn" onClick={runTest} disabled={running} style={{ marginTop: 6 }}>
          {running ? t('imp.trial.running') : t('ted.runTest')}
        </button>
        {testError && <div style={{ color: 'var(--danger)', fontSize: 12, marginTop: 6 }}>{testError}</div>}
        {testResult && <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 12, background: '#f9fafb', padding: 8, borderRadius: 6, marginTop: 6 }}>{testResult}</pre>}
      </div>
    </div>
  )
}
