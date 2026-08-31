import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import { CaretDown, CaretUp, ChatCircle, PaperPlaneTilt, X } from '@phosphor-icons/react'
import { listModels, sendConversationMessage, startConversationStream, subscribeConversationEvents } from '../api'
import type { ConversationMessage, Finding, Session } from '../types'
import { t, useLang } from '../i18n'
import { Button } from './ui/Button'
import { Markdown } from './Markdown'
import { readLocal, writeLocal } from '../lib/storage'

const DOCK_MIN = 160
const DOCK_MAX_OFFSET = 180

function effortLabel(value: string): string {
  const label = t(`effort.${value}`)
  return label.startsWith('effort.') ? value : label
}

function Bubble({ message }: { message: ConversationMessage }) {
  return (
    <div className={`chat-bubble chat-${message.role}`}>
      <div className="chat-bubble-head">
        <span className="bubble-dot" aria-hidden />
        {message.role === 'user' ? t('chat.you') : t('chat.ai')}
      </div>
      {message.content ? <Markdown content={message.content} /> : null}
    </div>
  )
}

export function AssistantDock({
  session,
  onCreate,
  onUpdate,
  onActionComplete,
}: {
  session: Session | null
  onCreate: () => Promise<Session>
  onUpdate: (patch: Partial<Session>) => void
  onActionComplete: () => void
}) {
  useLang()
  const [text, setText] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [efforts, setEfforts] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [busySeconds, setBusySeconds] = useState(0)
  const [collapsed, setCollapsed] = useState(false)
  const [closed, setClosed] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const [pending, setPending] = useState<{ tool: string; args: Record<string, unknown> } | null>(null)
  const [structuredResult, setStructuredResult] = useState<{
    tool?: string
    report?: string | null
    findings?: Finding[]
    stage_id?: string
    template_id?: string
  } | null>(null)
  const [error, setError] = useState('')
  const [height, setHeight] = useState(() => Number(readLocal('lattice.dockHeight', '')) || 320)
  const abortRef = useRef<AbortController | null>(null)
  const heightRef = useRef(height)

  useEffect(() => {
    heightRef.current = height
  }, [height])

  useEffect(() => {
    let cancelled = false
    const loadModels = () => {
      listModels()
        .then((r) => {
          if (cancelled) return
          setModels(r.models)
          setEfforts(r.efforts)
        })
        .catch(() => {
          if (cancelled) return
          setModels([])
          setEfforts([])
        })
    }
    loadModels()
    window.addEventListener('lattice:settings-changed', loadModels)
    return () => {
      cancelled = true
      window.removeEventListener('lattice:settings-changed', loadModels)
    }
  }, [])

  useEffect(() => {
    setText('')
    setStreamingText('')
    setPending(null)
    setStructuredResult(null)
    setError('')
  }, [session?.id])

  useEffect(() => {
    if (!busy) {
      setBusySeconds(0)
      return
    }
    const timer = setInterval(() => setBusySeconds((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [busy])

  function pause() {
    abortRef.current?.abort()
  }

  function close() {
    pause()
    setClosed(true)
    setCollapsed(false)
    // Remember the hide: the dock stays closed across reloads until the
    // user re-opens it via the fab or the sidebar toggle.
    writeLocal('lattice.ui.dock', '0')
  }

  function startResize(event: ReactMouseEvent) {
    event.preventDefault()
    const startY = event.clientY
    const startHeight = heightRef.current
    function onMove(ev: MouseEvent) {
      const next = Math.min(Math.max(startHeight + (startY - ev.clientY), DOCK_MIN), window.innerHeight - DOCK_MAX_OFFSET)
      heightRef.current = next
      setHeight(next)
    }
    function onUp() {
      writeLocal('lattice.dockHeight', String(heightRef.current))
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  async function send() {
    if (!text.trim() || busy) return
    let target = session
    if (!target) {
      target = await onCreate()
    }
    setError('')
    setStreamingText('')
    setPending(null)
    setStructuredResult(null)
    setBusy(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const { job_id } = await startConversationStream(target.id, text.trim(), undefined, controller.signal)
      const result = await subscribeConversationEvents(
        target.id,
        job_id,
        (event) => {
          if (event.type === 'content_delta') setStreamingText((prev) => prev + (event.content ?? ''))
        },
        controller.signal,
      )
      setPending(result.pending)
      onActionComplete()
    } catch (caught) {
      setError(controller.signal.aborted ? t('apie.cancelled') : String(caught))
    } finally {
      setBusy(false)
      setText('')
    }
  }

  async function confirm(approved: boolean) {
    if (!session || !pending) return
    if (!approved) {
      setPending(null)
      return
    }
    const confirm = pending
    setPending(null)
    setBusy(true)
    setError('')
    setStructuredResult(null)
    try {
      const result = await sendConversationMessage(session.id, '', { tool: confirm.tool, args: confirm.args })
      for (const event of result.events ?? []) {
        if (event.type !== 'tool_result') continue
        const data = event.data as { tool?: string; result?: Record<string, unknown> } | undefined
        const payload = data?.result as Record<string, unknown> | undefined
        if (!data?.tool || !payload) continue
        if (data.tool === 'try_tool') {
          setStructuredResult({
            tool: data.tool,
            report: payload.report as string | null,
            findings: payload.findings as Finding[] | undefined,
          })
        }
        if (data.tool === 'bind_tool') {
          setStructuredResult({
            tool: data.tool,
            stage_id: payload.stage_id as string | undefined,
            template_id: payload.template_id as string | undefined,
          })
        }
      }
      onActionComplete()
    } catch (caught) {
      setError(String(caught))
    } finally {
      setBusy(false)
    }
  }

  const messages = session?.messages ?? []
  const hasContent = messages.length > 0 || streamingText || pending || structuredResult || error

  if (closed) {
    return (
      <button
        className="assistant-fab"
        type="button"
        onClick={() => {
          writeLocal('lattice.ui.dock', '1')
          setClosed(false)
        }}
      >
        <ChatCircle size={16} weight="fill" />
        {t('dock.title')}
      </button>
    )
  }

  if (collapsed) {
    return (
      <div className="assistant-dock-collapsed">
        <ChatCircle size={15} weight="fill" />
        <span className="assistant-dock-collapsed-title">{t('dock.title')}</span>
        {busy && <span className="muted">{t('assistant.thinking')} {busySeconds}s</span>}
        <div className="toolbar-spacer" />
        <Button size="sm" variant="ghost" icon={<CaretUp size={14} weight="bold" />} onClick={() => setCollapsed(false)}>
          {t('dock.expand')}
        </Button>
      </div>
    )
  }

  return (
    <div className="assistant-dock" style={{ height }}>
      <div className="dock-resizer" role="separator" aria-orientation="horizontal" onMouseDown={startResize} title={t('dock.resize')} />
      <div className="assistant-dock-head">
        <span className="assistant-dock-head-title">
          <ChatCircle size={15} weight="fill" />
          {t('dock.title')}
          {session?.name && <span className="muted">· {session.name}</span>}
        </span>
        <div className="assistant-dock-head-actions">
          {busy && (
            <Button size="sm" variant="ghost" onClick={pause}>
              {t('dock.pause')}
            </Button>
          )}
          <button type="button" className="dock-icon-btn" aria-label={t('dock.collapse')} title={t('dock.collapse')} onClick={() => setCollapsed(true)}>
            <CaretDown size={15} weight="bold" />
          </button>
          <button type="button" className="dock-icon-btn" aria-label={t('dock.close')} title={t('dock.close')} onClick={close}>
            <X size={15} weight="bold" />
          </button>
        </div>
      </div>
      <div className="assistant-dock-log">
        {hasContent ? (
          <>
            {messages.map((m, i) => (
              <Bubble key={i} message={m} />
            ))}
            {streamingText && (
              <div className="chat-bubble chat-assistant">
                <div className="chat-bubble-head">
                  <span className="bubble-dot" aria-hidden />
                  {t('chat.ai')}
                </div>
                <Markdown content={streamingText} />
              </div>
            )}
            {pending && (
              <div className="analysis-report">
                <p className="muted">
                  {t('dock.pending')} {pending.tool} {JSON.stringify(pending.args)}
                </p>
                <div style={{ display: 'flex', gap: 8 }}>
                  <Button size="sm" variant="primary" onClick={() => void confirm(true)} disabled={busy}>
                    {t('dock.confirm')}
                  </Button>
                  <Button size="sm" onClick={() => void confirm(false)} disabled={busy}>
                    {t('dock.cancel')}
                  </Button>
                </div>
              </div>
            )}
            {structuredResult && (
              <div className="assistant-structured-result" style={{ marginTop: 8 }}>
                {structuredResult.report && <Markdown content={structuredResult.report} />}
                {(structuredResult.findings ?? []).map((finding) => (
                  <div key={finding.id} className="finding-row" style={{ marginTop: 6 }}>
                    <strong>{finding.severity}</strong> · {finding.title}
                    {finding.target && <span className="muted"> · {finding.target}</span>}
                  </div>
                ))}
                {structuredResult.stage_id && (
                  <div className="text-success">
                    {t('adock.boundToStage')
                      .replace('{template}', structuredResult.template_id ?? '')
                      .replace('{stage}', structuredResult.stage_id)}
                  </div>
                )}
              </div>
            )}
            {error && <div className="text-danger">{error}</div>}
          </>
        ) : (
          <div className="run-output-empty">{t('chat.empty')}</div>
        )}
      </div>
      <div className="assistant-dock-composer">
        <div className="composer-meta">
          <select className="select composer-select" value={session?.model ?? ''} onChange={(e) => onUpdate({ model: e.target.value })} aria-label={t('composer.model')}>
            <option value="">{t('llm.model.default')}</option>
            {session?.model && !models.includes(session.model) && <option value={session.model}>{session.model}</option>}
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <select
            className="select composer-select"
            value={session?.reasoning_effort ?? ''}
            onChange={(e) => onUpdate({ reasoning_effort: e.target.value })}
            aria-label={t('composer.effort')}
          >
            <option value="">{t('llm.effort.default')}</option>
            {session?.reasoning_effort && !efforts.includes(session.reasoning_effort) && (
              <option value={session.reasoning_effort}>{effortLabel(session.reasoning_effort)}</option>
            )}
            {efforts.map((e) => (
              <option key={e} value={e}>
                {effortLabel(e)}
              </option>
            ))}
          </select>
        </div>
        <textarea
          className="input"
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('composer.messagePlaceholder')}
          disabled={busy}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
        {busy && <span className="assistant-dock-thinking">{t('assistant.thinking')} {busySeconds}s</span>}
        <Button size="sm" variant="primary" icon={<PaperPlaneTilt size={15} weight="bold" />} onClick={send} disabled={busy || !text.trim()}>
          {t('composer.send')}
        </Button>
      </div>
    </div>
  )
}
