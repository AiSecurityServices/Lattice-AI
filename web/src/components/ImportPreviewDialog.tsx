import { useEffect, useState } from 'react'
import { applyAssetImport, previewAssetImport } from '../api'
import { Button } from './ui/Button'
import type { ImportAsset, ImportPreview, Template } from '../types'

export default function ImportPreviewDialog({
  source,
  template,
  onClose,
  onImported,
}: {
  source: string
  template: Template | null
  onClose: () => void
  onImported: () => void
}) {
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [bindings, setBindings] = useState<Record<string, string>>({})

  useEffect(() => {
    previewAssetImport(source).then(setPreview).catch((e) => setError(String(e)))
  }, [source])

  async function apply() {
    if (!preview) return
    setBusy(true)
    try {
      const accepted = preview.assets.filter((a) => a.type === 'skill' || bindings[a.name])
      const normalizedBindings = Object.entries(bindings)
        .filter(([tool]) => tool)
        .map(([tool, stageId]) => ({ tool, stage_id: stageId }))
      await applyAssetImport({ template_id: template?.id ?? '', preview, accepted_assets: accepted, bindings: normalizedBindings })
      onImported()
      onClose()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal">
      <div className="card">
        <h3>Import preview</h3>
        {error && <p className="text-danger">{error}</p>}
        {!preview ? <p>Loading...</p> : (
          <>
            <p className="muted">{preview.source}</p>
            {preview.assets.map((asset) => (
              <ImportAssetRow
                key={asset.name}
                asset={asset}
                template={template}
                value={bindings[asset.name] ?? ''}
                onChange={(stageId) => setBindings((prev) => ({ ...prev, [asset.name]: stageId }))}
              />
            ))}
            {preview.warnings.map((warning) => <p key={warning} className="text-warning">{warning}</p>)}
            <div className="card-actions">
              <Button size="sm" onClick={onClose}>Cancel</Button>
              <Button size="sm" variant="primary" loading={busy} onClick={apply}>Apply import</Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function ImportAssetRow({
  asset,
  template,
  value,
  onChange,
}: {
  asset: ImportAsset
  template: Template | null
  value: string
  onChange: (stageId: string) => void
}) {
  if (asset.type === 'skill') {
    return (
      <div className="card-desc">
        <strong>{asset.name}</strong> - Skill - {asset.description}
      </div>
    )
  }
  return (
    <div className="field">
      <span>{asset.name}</span>
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Do not bind</option>
        {(template?.stages ?? []).map((stage) => (
          <option key={stage.id} value={stage.id}>{stage.name}</option>
        ))}
      </select>
    </div>
  )
}
