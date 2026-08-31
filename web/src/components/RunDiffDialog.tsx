import { useState } from 'react'
import { diffRuns } from '../api'
import { t, useLang } from '../i18n'
import { Button } from './ui/Button'
import type { RunSummary } from '../types'

export function RunDiffDialog({ runs, headRunId, onClose }: { runs: RunSummary[]; headRunId: string; onClose: () => void }) {
  useLang()
  const [baseRunId, setBaseRunId] = useState('')
  const [result, setResult] = useState<Awaited<ReturnType<typeof diffRuns>> | null>(null)

  async function runDiff() {
    if (!baseRunId) return
    setResult(await diffRuns(baseRunId, headRunId))
  }

  return (
    <div className="dialog-backdrop" onMouseDown={onClose}>
      <div
        className="dialog dialog-wide"
        role="dialog"
        aria-modal="true"
        aria-label={t('rdiff.title')}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <h3>{t('rdiff.title')}</h3>
        <div className="field" style={{ marginBottom: 'var(--space-3)' }}>
          <select className="select" value={baseRunId} onChange={(e) => setBaseRunId(e.target.value)}>
            <option value="">{t('rdiff.selectBase')}</option>
            {runs.filter((r) => r.id !== headRunId).map((r) => (
              <option key={r.id} value={r.id}>{r.id} - {r.target}</option>
            ))}
          </select>
        </div>
        <div className="dialog-scroll">
          {result ? (
            <pre className="output-log-data">{JSON.stringify(result, null, 2)}</pre>
          ) : (
            <p className="muted">{t('rdiff.hint')}</p>
          )}
        </div>
        <div className="dialog-actions">
          <Button size="sm" variant="primary" onClick={runDiff} disabled={!baseRunId}>
            {t('rdiff.run')}
          </Button>
          <Button size="sm" onClick={onClose}>
            {t('common.close')}
          </Button>
        </div>
      </div>
    </div>
  )
}
