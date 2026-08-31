import { useEffect, useState } from 'react'
import { generateTemplate, saveTemplate, subscribeGenerateEvents } from '../api'
import { t, useLang } from '../i18n'
import type { GenerationReport, Template } from '../types'
import { Modal } from './ui/Modal'
import { Button } from './ui/Button'
import { Tag } from './ui/Tag'

type SourceMode = 'url' | 'path' | 'description'

export function GenerateTemplateDialog({
  open,
  onCancel,
  onApplied,
}: {
  open: boolean
  onCancel: () => void
  onApplied: () => void
}) {
  const [source, setSource] = useState('')
  const [mode, setMode] = useState<SourceMode>('url')
  const [description, setDescription] = useState('')
  const [name, setName] = useState('')
  const [progress, setProgress] = useState('')
  const [report, setReport] = useState<GenerationReport | null>(null)
  const [template, setTemplate] = useState<Template | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useLang()

  useEffect(() => {
    if (open) {
      setSource('')
      setDescription('')
      setProgress('')
      setReport(null)
      setTemplate(null)
      setError('')
      setBusy(false)
    }
  }, [open])

  async function run() {
    setBusy(true)
    setError('')
    setReport(null)
    setTemplate(null)
    setProgress(t('gen.progress.submitting'))
    try {
      const payload = mode === 'description' ? { description, name } : { source, mode, name }
      const { job_id } = await generateTemplate(payload)
      await subscribeGenerateEvents(job_id, (event) => {
        if (event.message) setProgress(event.message)
        if (event.type === 'complete' && event.template && event.report) {
          setTemplate(event.template)
          setReport(event.report)
        }
        if (event.type === 'error') setError(event.message ?? t('gen.error.failed'))
      })
    } catch (caught) {
      setError(String(caught))
    } finally {
      setBusy(false)
    }
  }

  async function apply() {
    if (!template) return
    await saveTemplate(template.id, template)
    onApplied()
  }

  if (!open) return null

  const canSubmit = mode === 'description' ? !!description.trim() : !!source.trim()
  const confidenceTone = report?.confidence === 'high' ? 'success' : report?.confidence === 'medium' ? 'warning' : 'neutral'

  return (
    <Modal open={open} onClose={onCancel} ariaLabel={t('gen.title')} wide>
      <h3 className="dialog-title">{t('gen.title')}</h3>

        {!template && (
          <>
            <div className="field">
              <span>{t('gen.source')}</span>
              <div className="gen-source-modes">
                {(['url', 'path', 'description'] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    className={`gen-mode${mode === m ? ' active' : ''}`}
                    onClick={() => setMode(m)}
                  >
                    {m === 'description' ? t('gen.mode.description') : m === 'url' ? t('gen.mode.url') : t('gen.mode.path')}
                  </button>
                ))}
              </div>
            </div>
            {mode !== 'description' ? (
              <div className="field">
                <span>{mode === 'url' ? t('gen.source.url') : t('gen.mode.path')}</span>
                <input
                  className="input"
                  value={source}
                  onChange={(event) => setSource(event.target.value)}
                  placeholder={mode === 'url' ? t('gen.source.url.placeholder') : 'C:\\path\\to\\project'}
                />
              </div>
            ) : (
              <div className="field">
                <span>{t('gen.description')}</span>
                <textarea
                  className="textarea"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  rows={4}
                  placeholder={t('gen.description.placeholder')}
                />
              </div>
            )}
            <div className="field">
              <span>{t('gen.name')}</span>
              <input className="input" value={name} onChange={(event) => setName(event.target.value)} />
            </div>
            {progress && <div className="gen-progress">{progress}</div>}
            {error && <div className="text-danger">{error}</div>}
            <div className="dialog-actions">
              <Button onClick={onCancel} disabled={busy}>
                {t('common.cancel')}
              </Button>
              <Button variant="primary" onClick={run} loading={busy} disabled={busy || !canSubmit}>
                {busy ? t('gen.progress.running') : t('gen.generate')}
              </Button>
            </div>
          </>
        )}

        {template && report && (
          <>
            <div className="gen-summary">
              <div className="gen-template-name">{template.name}</div>
              <Tag tone={confidenceTone}>{t('gen.confidence').replace('{level}', String(report.confidence ?? 'low'))}</Tag>
            </div>
            <div className="gen-summary-stats">
              {t('gen.summary.stats')
                .replace('{stages}', String(template.stages.length))
                .replace('{connections}', String(template.stages.reduce((n, s) => n + (s.depends_on ?? []).length, 0)))
                .replace('{tools}', String(template.tools.length))
                .replace('{skills}', String((template.skills ?? []).length))}
            </div>
            {(report.imports?.tools.length ?? 0) > 0 && (
              <div className="gen-section">
                <div className="gen-section-title">{t('gen.imports.title')}</div>
                {report.imports!.tools.map((tool) => (
                  <div key={tool.name} className="gen-import">
                    <Tag>{tool.kind}</Tag>
                    <b>{tool.name}</b>
                    <span className="muted">{tool.status}</span>
                  </div>
                ))}
              </div>
            )}
            {(report.issues ?? []).length > 0 && (
              <div className="gen-section">
                <div className="gen-section-title">{t('gen.issues.title')}</div>
                {report.issues!.map((issue, index) => (
                  <div key={index} className={`gen-issue ${issue.severity}`}>
                    <b>{issue.where}</b> [{issue.severity}] {issue.message}
                    {issue.resolution ? ` → ${issue.resolution}` : ''}
                  </div>
                ))}
              </div>
            )}
            <div className="dialog-actions">
              <Button onClick={() => { setTemplate(null); setReport(null) }}>
                {t('gen.back')}
              </Button>
              <Button variant="primary" onClick={apply}>
                {t('gen.apply')}
              </Button>
            </div>
          </>
        )}
    </Modal>
  )
}
