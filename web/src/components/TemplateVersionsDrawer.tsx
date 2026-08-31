import { useEffect, useState } from 'react'
import { getTemplate, getTemplateVersion, listTemplateVersions, restoreTemplateVersion, type TemplateVersionInfo } from '../api'
import { diffTemplates, type TemplateDiff } from '../templateDiff'
import { formatTime } from '../lib/format'
import { t, useLang } from '../i18n'
import type { Template } from '../types'
import { Modal } from './ui/Modal'
import { Button } from './ui/Button'

// Evaluated at render time so lineage labels follow the active language.
function lineageLabels(): Record<string, string> {
  return {
    manual: t('tvd.lineage.manual'),
    refine: t('tvd.lineage.refine'),
    selfcheck: t('tvd.lineage.selfcheck'),
    import: t('tvd.lineage.import'),
  }
}

/**
 * Version history drawer (I3): paged version list with lineage badges, a
 * client-side diff of any version against the current one (templateDiff),
 * and n8n-style restore that copies a historical version on top of the chain.
 */
export default function TemplateVersionsDrawer({
  templateId,
  onClose,
  onRestored,
}: {
  templateId: string
  onClose: () => void
  onRestored?: (newVersion: number) => void
}) {
  useLang()
  const [versions, setVersions] = useState<TemplateVersionInfo[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [currentTemplate, setCurrentTemplate] = useState<Template | null>(null)
  const [diffFor, setDiffFor] = useState<number | null>(null)
  const [diff, setDiff] = useState<TemplateDiff | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const pageSize = 20

  async function load(nextOffset = offset) {
    setError('')
    try {
      const page = await listTemplateVersions(templateId, nextOffset, pageSize)
      setVersions(page.versions)
      setTotal(page.total)
      setOffset(nextOffset)
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    setDiffFor(null)
    setDiff(null)
    setMessage('')
    load(0)
    getTemplate(templateId)
      .then(setCurrentTemplate)
      .catch(() => setCurrentTemplate(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateId])

  async function toggleDiff(version: number) {
    if (diffFor === version) {
      setDiffFor(null)
      setDiff(null)
      return
    }
    setError('')
    try {
      const historical = await getTemplateVersion(templateId, version)
      if (!currentTemplate) throw new Error('no current template')
      setDiff(diffTemplates(currentTemplate, historical.template))
      setDiffFor(version)
    } catch (e) {
      setError(String(e))
    }
  }

  async function restore(version: number) {
    setBusy(true)
    setError('')
    try {
      const result = await restoreTemplateVersion(templateId, version)
      setMessage(`${t('evo.versions.restored')} v${result.new_version}`)
      await load(0)
      getTemplate(templateId)
        .then(setCurrentTemplate)
        .catch(() => {})
      onRestored?.(result.new_version)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open onClose={onClose} ariaLabel={t('evo.versions.title')} wide>
      <div className="run-panel-header">
        <h3>{t('evo.versions.title')}</h3>
        <Button size="sm" variant="ghost" aria-label={t('common.close')} onClick={onClose}>✕</Button>
      </div>
      {message && <p className="text-success">{message}</p>}
      {error && <p className="text-danger">{error}</p>}
      <p className="muted">
        {t('evo.versions.total')}: {total}
      </p>
      <ul className="version-list">
        {versions.map((item) => (
          <li key={item.version} className="version-row">
            <span className="version-no">v{item.version}</span>
            <span className="tag">{lineageLabels()[item.lineage?.source] ?? item.lineage?.source ?? 'manual'}</span>
            {item.current && <span className="tag success">{t('evo.versions.current')}</span>}
            <span className="muted">{formatTime(item.saved_at)}</span>
            <span className="version-actions">
              {/* Diffing the current version against itself is noise. */}
              {!item.current && (
                <Button size="sm" onClick={() => void toggleDiff(item.version)}>
                  {diffFor === item.version ? t('evo.versions.hideDiff') : t('evo.versions.diff')}
                </Button>
              )}
              {!item.current && (
                <Button size="sm" variant="primary" loading={busy} onClick={() => void restore(item.version)}>
                  {t('evo.versions.restore')}
                </Button>
              )}
            </span>
              {diffFor === item.version && diff && (
                <div className="evo-diff version-diff">
                  {diff.changedConnections.length === 0 ? (
                    <span className="muted">{t('evo.diff.none')}</span>
                  ) : (
                    <ul>
                      {diff.changedConnections.map((change) => (
                        <li key={change.id}>
                          <strong>{change.id}</strong>: {change.before.join(t('tplp.joiner')) || '∅'} →{' '}
                          {change.after.join(t('tplp.joiner')) || '∅'}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
        {total > pageSize && (
          <div className="card-actions">
            <Button size="sm" disabled={offset === 0} onClick={() => void load(Math.max(0, offset - pageSize))}>
              {t('evo.versions.prev')}
            </Button>
            <Button size="sm" disabled={offset + pageSize >= total} onClick={() => void load(offset + pageSize)}>
              {t('evo.versions.next')}
            </Button>
          </div>
        )}
    </Modal>
  )
}
