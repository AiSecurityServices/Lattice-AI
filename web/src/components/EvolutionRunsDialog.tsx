import { useEffect, useState } from 'react'
import { listEvolutionRuns, type EvolutionRunSummary } from '../api'
import { formatTime } from '../lib/format'
import { t, useLang } from '../i18n'
import { Modal } from './ui/Modal'
import { Button } from './ui/Button'

/**
 * TemplatesPage entry dialog (I4): recent runs of this template that carry
 * self-check suggestions; each row deep-links to the run's report on RunPage
 * via #/run?template=<id>&run=<run_id>.
 */
export default function EvolutionRunsDialog({
  templateId,
  templateName,
  onClose,
}: {
  templateId: string
  templateName: string
  onClose: () => void
}) {
  useLang()
  const [runs, setRuns] = useState<EvolutionRunSummary[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    listEvolutionRuns(templateId)
      .then((res) => {
        if (alive) setRuns(res.runs)
      })
      .catch((e) => {
        if (alive) setError(String(e))
      })
    return () => {
      alive = false
    }
  }, [templateId])

  function openRun(runId: string) {
    window.location.hash = `/run?template=${encodeURIComponent(templateId)}&run=${encodeURIComponent(runId)}`
    onClose()
  }

  return (
    <Modal open onClose={onClose} ariaLabel={t('evo.runs.title')} wide>
      <div className="run-panel-header">
        <h3>{t('evo.runs.title')}</h3>
        <Button size="sm" variant="ghost" aria-label={t('common.close')} onClick={onClose}>✕</Button>
      </div>
      <p className="muted">{templateName}</p>
      {error && <p className="text-danger">{error}</p>}
      {runs.length === 0 ? (
        <p className="muted">{t('evo.runs.empty')}</p>
      ) : (
        <ul className="version-list">
          {runs.map((run) => (
            <li key={run.run_id} className="version-row">
              <span className="version-no">{run.run_id.slice(0, 8)}</span>
              <span className="muted">{formatTime(run.created_at)}</span>
              <span>{run.target}</span>
              <span className="tag">
                {t('evo.runs.count')}: {run.suggestion_count}
              </span>
              <span className="version-actions">
                <Button size="sm" variant="primary" onClick={() => openRun(run.run_id)}>
                  {t('evo.runs.open')}
                </Button>
              </span>
              {run.summary && <div className="card-desc">{run.summary}</div>}
            </li>
          ))}
        </ul>
      )}
    </Modal>
  )
}
