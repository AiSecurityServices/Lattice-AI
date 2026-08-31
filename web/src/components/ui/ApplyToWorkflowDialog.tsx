import { useEffect, useState } from 'react'
import { saveTemplate } from '../../api'
import { t, useLang } from '../../i18n'
import { newToolBindingId } from '../../lib/toolBinding'
import type { Template } from '../../types'
import { Button } from './Button'
import { SegmentedControl } from './SegmentedControl'

export function ApplyToWorkflowDialog({
  open,
  kind,
  items,
  template,
  onCancel,
  onApplied,
}: {
  open: boolean
  kind: 'tool' | 'skill'
  items: string[]
  template: Template | null
  onCancel: () => void
  onApplied: () => void
}) {
  const [scope, setScope] = useState<'all' | 'stage'>('all')
  const [stageId, setStageId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useLang()

  useEffect(() => {
    if (open) {
      setScope('all')
      setStageId(template?.stages?.[0]?.id ?? '')
      setError('')
    }
  }, [open, template])

  if (!open) return null

  async function apply() {
    if (!template) return
    setBusy(true)
    setError('')
    const targetIds = scope === 'all' ? template.stages.map((s) => s.id) : stageId ? [stageId] : []
    if (targetIds.length === 0) {
      setError(t('apply.stage.required'))
      setBusy(false)
      return
    }

    const updated: Template = {
      ...template,
      stages: template.stages.map((stage) => {
        if (!targetIds.includes(stage.id)) return stage
        if (kind === 'tool') {
          const existing = (stage.tools ?? []).map((b) => b.tool)
          const additions = items
            .filter((name) => !existing.includes(name))
            .map((tool) => ({ tool, key: newToolBindingId(), note: '' }))
          if (additions.length === 0) return stage
          return { ...stage, tools: [...(stage.tools ?? []), ...additions] }
        }
        const existing = (stage.skills ?? []).map((sb) => sb.skill)
        const additions = items.filter((name) => !existing.includes(name)).map((skill) => ({ skill }))
        if (additions.length === 0) return stage
        return { ...stage, skills: [...(stage.skills ?? []), ...additions] }
      }),
    }

    try {
      await saveTemplate(template.id, updated)
      onApplied()
    } catch (caught) {
      setError(String(caught))
    } finally {
      setBusy(false)
    }
  }

  const label = kind === 'tool' ? t('apply.kind.tool') : 'Skill'
  const title = t('apply.title').replace('{kind}', label)

  return (
    <div className="dialog-backdrop" onMouseDown={onCancel}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <h3 className="dialog-title">{title}</h3>
        <p className="muted">
          {t('apply.items.desc').replace('{kind}', label).replace('{items}', items.join(t('tplp.joiner')))}
        </p>
        <div className="field">
          <span>{t('apply.scope.label')}</span>
          <SegmentedControl
            options={[
              { value: 'all' as const, label: t('apply.scope.all') },
              { value: 'stage' as const, label: t('apply.scope.stage') },
            ]}
            value={scope}
            onChange={(value) => setScope(value)}
            ariaLabel={t('apply.scope.aria')}
          />
        </div>
        {scope === 'stage' && (
          <div className="field">
            <span>{t('apply.target.stage')}</span>
            <select className="select" value={stageId} onChange={(event) => setStageId(event.target.value)}>
              {template?.stages.map((stage) => (
                <option key={stage.id} value={stage.id}>
                  {stage.name}
                </option>
              ))}
            </select>
          </div>
        )}
        {error && <div className="text-danger">{error}</div>}
        <div className="dialog-actions">
          <Button onClick={onCancel} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" onClick={apply} loading={busy} disabled={!template}>
            {busy ? t('apply.applying') : t('evo.card.apply')}
          </Button>
        </div>
      </div>
    </div>
  )
}
