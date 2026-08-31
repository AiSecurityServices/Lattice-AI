import { useEffect, useState } from 'react'
import { PaperPlaneTilt, Play } from '@phosphor-icons/react'
import type { Session, SessionKind } from '../types'
import { t, useLang } from '../i18n'
import { Button } from './ui/Button'

function effortLabel(value: string): string {
  const label = t(`effort.${value}`)
  return label.startsWith('effort.') ? value : label
}

function HelpDot({ id, label, tip }: { id: string; label: string; tip: string }) {
  return (
    <span className="help-dot" tabIndex={0} role="button" aria-label={label} aria-describedby={id}>
      ?
      <span className="help-tip" id={id} role="tooltip">
        {tip}
      </span>
    </span>
  )
}

export function ConversationDock({
  session,
  busy,
  models,
  efforts,
  onSubmit,
  onUpdate,
  onCancel,
  onStop,
}: {
  session: Session
  busy: boolean
  models: string[]
  efforts: string[]
  onSubmit: (text: string, kind: SessionKind) => void
  onUpdate: (patch: Partial<Session>) => void
  onCancel: () => void
  onStop?: () => void
}) {
  useLang()
  const [value, setValue] = useState('')
  const [target, setTarget] = useState(session.target ?? '')
  const isTask = session.kind === 'task'

  useEffect(() => {
    setValue('')
    setTarget(session.target ?? '')
  }, [session.id])

  const submit = () => {
    if (!value.trim() || busy) return
    onSubmit(value.trim(), session.kind)
    setValue('')
  }

  return (
    <div className="composer composer-chat">
      <div className="composer-meta">
        <select className="select composer-select" aria-label={t('composer.model')} value={session.model} onChange={(e) => onUpdate({ model: e.target.value })}>
          <option value="">{t('llm.model.default')}</option>
          {session.model && !models.includes(session.model) && <option value={session.model}>{session.model}</option>}
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <select className="select composer-select" aria-label={t('composer.effort')} value={session.reasoning_effort} onChange={(e) => onUpdate({ reasoning_effort: e.target.value })}>
          <option value="">{t('llm.effort.default')}</option>
          {session.reasoning_effort && !efforts.includes(session.reasoning_effort) && (
            <option value={session.reasoning_effort}>{effortLabel(session.reasoning_effort)}</option>
          )}
          {efforts.map((e) => (
            <option key={e} value={e}>
              {effortLabel(e)}
            </option>
          ))}
        </select>
        {isTask && (
          <>
            <label className="composer-autonomous">
              <input type="checkbox" checked={session.autonomous} onChange={(e) => onUpdate({ autonomous: e.target.checked })} />
              {t('composer.autonomous')}
              <HelpDot
                id="autonomous-hint"
                label={t('composer.autonomous.hint')}
                tip={t('composer.autonomous.tip')}
              />
            </label>
            <label className="composer-autonomous">
              <input type="checkbox" checked={session.self_check ?? false} onChange={(e) => onUpdate({ self_check: e.target.checked })} />
              {t('composer.selfcheck')}
              <HelpDot
                id="selfcheck-hint"
                label={t('composer.selfcheck.hint')}
                tip={t('composer.selfcheck.tip')}
              />
            </label>
          </>
        )}
      </div>

      <div className="composer-body">
        {isTask ? (
          <input
            className="input composer-input"
            value={target}
            onChange={(e) => {
              setTarget(e.target.value)
              onUpdate({ target: e.target.value })
            }}
            placeholder={t('composer.targetPlaceholder')}
            disabled={busy}
            aria-label={t('composer.target')}
          />
        ) : (
          <textarea
            className="input composer-input"
            rows={2}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            placeholder={t('composer.messagePlaceholder')}
            disabled={busy}
          />
        )}
        <div className="composer-buttons">
          {isTask ? (
            <Button variant="primary" icon={<Play size={15} weight="bold" />} onClick={() => onSubmit(target.trim(), 'task')} disabled={busy || !target.trim()}>
              {t('composer.run')}
            </Button>
          ) : (
            <Button variant="primary" icon={<PaperPlaneTilt size={15} weight="bold" />} onClick={submit} disabled={busy || !value.trim()}>
              {t('composer.send')}
            </Button>
          )}
          {busy && (
            <Button variant="danger" onClick={isTask ? (onStop ?? onCancel) : onCancel}>
              {isTask ? t('composer.pause') : t('composer.cancel')}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
