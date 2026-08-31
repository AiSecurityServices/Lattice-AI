import { useState } from 'react'
import { CaretDown } from '@phosphor-icons/react'
import { saveTemplate } from '../api'
import Designer from '../Designer'
import { t, useLang } from '../i18n'
import { Button } from '../components/ui/Button'
import type { Template } from '../types'

export default function WorkflowPage({
  template,
  onTemplateChange,
}: {
  template: Template | null
  onTemplateChange: (t: Template) => void
}) {
  useLang()
  const [showSummary, setShowSummary] = useState(false)

  async function save(t?: Template) {
    const toSave = t ?? template
    if (!toSave) return
    await saveTemplate(toSave.id, toSave)
  }

  return (
    <div className="page">
      <div className="workflow-toolbar">
        <Button
          size="sm"
          variant="ghost"
          icon={<CaretDown size={13} weight="bold" style={{ transform: showSummary ? undefined : 'rotate(-90deg)' }} />}
          onClick={() => setShowSummary((value) => !value)}
        >
          {t('wf.description')}
        </Button>
      </div>

      {showSummary && template && (
        <div className="workflow-summary">
          {template.summary ? <pre>{template.summary}</pre> : <p className="muted">{t('wf.summary.empty')}</p>}
        </div>
      )}

      <div className="designer-body">
        {template ? (
          <Designer template={template} onTemplateChange={onTemplateChange} onSave={save} />
        ) : (
          <p className="muted workflow-empty">{t('wf.empty')}</p>
        )}
      </div>
    </div>
  )
}
