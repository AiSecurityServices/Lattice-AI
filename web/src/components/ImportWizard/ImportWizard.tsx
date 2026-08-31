import { useState } from 'react'
import {
  confirmImport,
  executeImportedTool,
  generateOutputSchema,
  inspectImport,
  saveImportedTool,
  tryImportedTool,
} from '../../api'
import { t, useLang } from '../../i18n'
import type { ImportInspectResult, Tool } from '../../types'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'

export type WizardStep = 'entry' | 'inspect' | 'preview' | 'trial' | 'save' | 'done'

const STEPS: WizardStep[] = ['entry', 'inspect', 'preview', 'trial', 'save']

const SCOPE_OPTIONS = ['web', 'host', 'network', 'service']
const APPROVAL_OPTIONS: Tool['approval'][] = ['allow', 'ask', 'deny']
const CATEGORIES = ['general', 'recon', 'vuln', 'fuzz']

/**
 * Five-step import wizard: paste → inspect (four-state) → preview → trial run
 * → store. The backend sniffs the content, so the wizard never decides the
 * source type itself. Pending drafts go straight to the confirm endpoint
 * (fill secrets → store); completed drafts walk preview/trial/save.
 */
export default function ImportWizard({
  onClose,
  onImported,
}: {
  onClose: () => void
  onImported?: (tool: Tool) => void
}) {
  useLang()
  const [step, setStep] = useState<WizardStep>('entry')
  const [content, setContent] = useState('')
  const [inspect, setInspect] = useState<ImportInspectResult | null>(null)
  const [draft, setDraft] = useState<Tool | null>(null)
  const [secretFills, setSecretFills] = useState<Record<string, string>>({})
  const [target, setTarget] = useState('')
  const [trialResult, setTrialResult] = useState<Record<string, unknown> | null>(null)
  const [sampleOutput, setSampleOutput] = useState('')
  const [schemaHint, setSchemaHint] = useState('')
  const [name, setName] = useState('')
  const [category, setCategory] = useState('general')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function runInspect() {
    setBusy(true)
    setError('')
    try {
      const result = await inspectImport(content)
      setInspect(result)
      setDraft((result.draft as Tool | null) ?? null)
      setSecretFills({})
      setStep('inspect')
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function confirmPending() {
    if (!inspect?.draft_id) return
    setBusy(true)
    setError('')
    try {
      const saved = await confirmImport({ draft_id: inspect.draft_id, fills: { secrets: secretFills } })
      finish(saved.tool)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function runTrial() {
    if (!draft) return
    setBusy(true)
    setError('')
    try {
      const approval = await tryImportedTool(draft, target)
      const result = await executeImportedTool(approval.approval_id)
      setTrialResult(result.result)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function deriveSchema() {
    if (!draft || !sampleOutput.trim()) return
    setBusy(true)
    setError('')
    try {
      const { output } = await generateOutputSchema(draft, sampleOutput)
      setDraft({ ...draft, output })
      setSchemaHint(t('imp.trial.sampleOk'))
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function storeTool() {
    if (!draft) return
    setBusy(true)
    setError('')
    try {
      const toStore = { ...draft, name: name.trim() || draft.name, category }
      const saved = await saveImportedTool(toStore)
      finish({ ...toStore, name: saved.name })
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  function finish(tool: Tool) {
    setStep('done')
    onImported?.(tool)
  }

  const activeIndex = STEPS.indexOf(step === 'done' ? 'save' : step)

  return (
    <Modal open onClose={onClose} ariaLabel={t('imp.wizard.title')} wide>
      <h3>{t('imp.wizard.title')}</h3>
        <ol className="wizard-steps">
          {STEPS.map((s, i) => (
            <li key={s} className={i === activeIndex ? 'active' : ''}>
              {t(`imp.step.${s}`)}
            </li>
          ))}
        </ol>
        {error && <p className="text-danger">{error}</p>}

        {step === 'entry' && (
          <div>
            <p className="muted">{t('imp.entry.title')}</p>
            <textarea
              className="input"
              rows={6}
              placeholder={t('imp.entry.placeholder')}
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
            <div className="card-actions">
              <Button size="sm" onClick={onClose}>{t('common.cancel')}</Button>
              <Button size="sm" variant="primary" loading={busy} disabled={!content.trim()} onClick={runInspect}>
                {t('imp.entry.next')}
              </Button>
            </div>
          </div>
        )}

        {step === 'inspect' && inspect && (
          <div>
            <p>
              <strong>{t(`imp.state.${inspect.status}`)}</strong>
            </p>
            {inspect.status === 'failed' && (
              <div>
                <p className="text-danger">{inspect.reason}</p>
                <p className="muted">{t('imp.failed.hint')}</p>
              </div>
            )}
            {inspect.status === 'pending' && (
              <div>
                {inspect.missing?.tools && inspect.missing.tools.length > 0 && (
                  <p className="muted">
                    {t('imp.missing.tools')}: {inspect.missing.tools.join(', ')}
                  </p>
                )}
                {(inspect.missing?.secrets ?? []).map((secret) => (
                  <div className="field" key={secret}>
                    <label htmlFor={`secret-${secret}`}>{t('imp.missing.secrets')}: {secret}</label>
                    <input
                      id={`secret-${secret}`}
                      className="input"
                      type="password"
                      value={secretFills[secret] ?? ''}
                      onChange={(e) => setSecretFills((prev) => ({ ...prev, [secret]: e.target.value }))}
                    />
                  </div>
                ))}
                <div className="card-actions">
                  <Button size="sm" onClick={() => setStep('entry')}>{t('imp.back')}</Button>
                  <Button size="sm" variant="primary" loading={busy} onClick={confirmPending}>
                    {t('imp.save.submit')}
                  </Button>
                </div>
              </div>
            )}
            {(inspect.status === 'completed' || inspect.status === 'completed_with_warnings') && (
              <div>
                {(inspect.warnings ?? []).map((w) => (
                  <p key={w} className="text-warning">
                    {t('imp.warnings')}: {w}
                  </p>
                ))}
                <div className="card-actions">
                  <Button size="sm" onClick={() => setStep('entry')}>{t('imp.back')}</Button>
                  <Button size="sm" variant="primary" onClick={() => setStep('preview')}>
                    {t('imp.next')}
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {step === 'preview' && draft && (
          <div>
            <p>
              <strong>{draft.name}</strong> <span className="tag">{draft.runner}</span>
            </p>
            {draft.description && <p className="card-desc">{draft.description}</p>}
            {draft.command && draft.command.length > 0 && (
              <p className="card-desc">
                <code>{draft.command.join(' ')}</code>
              </p>
            )}
            <details>
              <summary>{t('imp.preview.parameters')}</summary>
              <pre className="card-desc">{JSON.stringify(draft.parameters ?? {}, null, 2)}</pre>
            </details>
            <details>
              <summary>{t('imp.preview.output')}</summary>
              <pre className="card-desc">{JSON.stringify(draft.output ?? {}, null, 2)}</pre>
            </details>
            {(draft.secret_fields ?? []).length > 0 && (
              <p className="muted">
                {t('imp.preview.secretFields')}: {draft.secret_fields?.join(', ')}
              </p>
            )}
            <div className="field">
              <label htmlFor="imp-approval">{t('imp.preview.approval')}</label>
              <select
                id="imp-approval"
                className="select"
                value={draft.approval ?? 'ask'}
                onChange={(e) => setDraft({ ...draft, approval: e.target.value as Tool['approval'] })}
              >
                {APPROVAL_OPTIONS.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <span>{t('imp.preview.scope')}</span>
              <div>
                {SCOPE_OPTIONS.map((option) => (
                  <label key={option} style={{ marginRight: 12 }}>
                    <input
                      type="checkbox"
                      checked={(draft.scope ?? []).includes(option)}
                      onChange={(e) => {
                        const scope = new Set(draft.scope ?? [])
                        if (e.target.checked) scope.add(option)
                        else scope.delete(option)
                        setDraft({ ...draft, scope: [...scope] })
                      }}
                    />{' '}
                    {option}
                  </label>
                ))}
              </div>
            </div>
            <div className="card-actions">
              <Button size="sm" onClick={() => setStep('inspect')}>{t('imp.back')}</Button>
              <Button size="sm" variant="primary" onClick={() => setStep('trial')}>{t('imp.next')}</Button>
            </div>
          </div>
        )}

        {step === 'trial' && draft && (
          <div>
            <div className="field">
              <label htmlFor="imp-target">{t('imp.trial.target')}</label>
              <input
                id="imp-target"
                className="input"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              />
            </div>
            <div className="card-actions">
              <Button size="sm" loading={busy} disabled={!target.trim()} onClick={runTrial}>
                {t('imp.trial.run')}
              </Button>
            </div>
            {trialResult && (
              <pre className="card-desc">{JSON.stringify(trialResult, null, 2)}</pre>
            )}
            <p className="muted">{t('imp.trial.schemaBtn')}</p>
            <textarea
              className="input"
              rows={3}
              placeholder={t('imp.trial.sample')}
              value={sampleOutput}
              onChange={(e) => setSampleOutput(e.target.value)}
            />
            <div className="card-actions">
              <Button size="sm" loading={busy} disabled={!sampleOutput.trim()} onClick={deriveSchema}>
                AI schema
              </Button>
              {schemaHint && <span className="muted">{schemaHint}</span>}
            </div>
            <div className="card-actions">
              <Button size="sm" onClick={() => setStep('preview')}>{t('imp.back')}</Button>
              <Button size="sm" variant="primary" onClick={() => setStep('save')}>{t('imp.next')}</Button>
            </div>
          </div>
        )}

        {step === 'save' && draft && (
          <div>
            <div className="field">
              <label htmlFor="imp-name">{t('imp.save.name')}</label>
              <input id="imp-name" className="input" value={name} placeholder={draft.name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="imp-category">{t('imp.save.category')}</label>
              <select id="imp-category" className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORIES.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </div>
            <div className="card-actions">
              <Button size="sm" onClick={() => setStep('trial')}>{t('imp.back')}</Button>
              <Button size="sm" variant="primary" loading={busy} onClick={storeTool}>
                {t('imp.save.submit')}
              </Button>
            </div>
          </div>
        )}

        {step === 'done' && (
          <div>
            <p>
              <strong>{t('imp.done.title')}</strong>
            </p>
            <p className="muted">{t('imp.done.desc')}</p>
            <div className="card-actions">
              <Button size="sm" variant="primary" onClick={onClose}>{t('common.close')}</Button>
            </div>
          </div>
        )}
    </Modal>
  )
}
