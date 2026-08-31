import { useEffect, useState } from 'react'
import { previewSuggestion, applyWorkflowSuggestion } from '../api'
import { diffTemplates, type TemplateDiff } from '../templateDiff'
import { t, useLang } from '../i18n'
import type { EvolutionReport, EvolutionSuggestion, Template } from '../types'
import { Button } from './ui/Button'

/**
 * Evolution loop panel (I4): renders each self-check suggestion as a card
 * with a live diff preview (suggestion applied to a copy of the template via
 * /api/templates/preview-suggestion, diffed client-side) and a per-suggestion
 * apply button that snapshots the template with lineage source=selfcheck.
 */
export default function EvolutionPanel({
  template,
  evolution,
  onApplied,
}: {
  template: Template | null
  evolution: EvolutionReport | null
  onApplied?: (newVersion: number | undefined) => void
}) {
  useLang()
  const [previews, setPreviews] = useState<Record<number, TemplateDiff | null>>({})
  const [appliedVersion, setAppliedVersion] = useState<number | null>(null)
  const [busyIndex, setBusyIndex] = useState<number | null>(null)
  const [error, setError] = useState('')

  const suggestions = evolution?.suggestions ?? []

  useEffect(() => {
    setAppliedVersion(null)
    setPreviews({})
    if (!template || suggestions.length === 0) return
    let alive = true
    suggestions.forEach((suggestion, index) => {
      previewSuggestion(template, suggestion as unknown as Record<string, unknown>)
        .then(({ template: updated }) => {
          if (alive) setPreviews((prev) => ({ ...prev, [index]: diffTemplates(template, updated) }))
        })
        .catch(() => {
          if (alive) setPreviews((prev) => ({ ...prev, [index]: null }))
        })
    })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template?.id, template?.version, evolution])

  if (suggestions.length === 0) return null

  async function apply(suggestion: EvolutionSuggestion, index: number) {
    if (!template) return
    setBusyIndex(index)
    setError('')
    try {
      const result = await applyWorkflowSuggestion(template.id, suggestion as unknown as Record<string, unknown>)
      setAppliedVersion(result.new_version ?? null)
      onApplied?.(result.new_version)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusyIndex(null)
    }
  }

  return (
    <div className="evo-panel" role="region" aria-label={t('evo.panel.title')}>
      <div className="run-panel-header">
        <span className="run-panel-title">{t('evo.panel.title')}</span>
        {appliedVersion != null && (
          <span className="text-success">
            {t('evo.panel.applied')} v{appliedVersion}
          </span>
        )}
      </div>
      {error && <p className="text-danger">{error}</p>}
      {suggestions.map((suggestion, index) => {
        const diff = previews[index]
        return (
          <div key={index} className="card evo-card">
            <div className="evo-card-head">
              <span className="tag">{suggestion.type}</span>
              {suggestion.stage_id && <span className="muted">{suggestion.stage_id}</span>}
              <Button
                size="sm"
                variant="primary"
                loading={busyIndex === index}
                onClick={() => void apply(suggestion, index)}
              >
                {t('evo.card.apply')}
              </Button>
            </div>
            {suggestion.detail && <div className="card-desc">{suggestion.detail}</div>}
            <div className="evo-diff">
              {diff == null ? (
                <span className="muted">{t('evo.diff.unavailable')}</span>
              ) : diff.changedConnections.length === 0 ? (
                <span className="muted">{t('evo.diff.none')}</span>
              ) : (
                <ul>
                  {diff.changedConnections.map((change) => (
                    <li key={change.id}>
                      <strong>{change.id}</strong>: {change.before.join('、') || '∅'} →{' '}
                      {change.after.join('、') || '∅'}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
