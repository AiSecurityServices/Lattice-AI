import { useState, type ReactNode } from 'react'
import { CaretRight, CircleNotch, ClockCounterClockwise, ListChecks, MagnifyingGlass, X } from '@phosphor-icons/react'
import type { StageExecutionRow } from '../../api'
import { Skeleton } from '../ui/Skeleton'
import { t } from '../../i18n'

export interface DrawerToolEvent {
  kind: 'call' | 'result'
  tool: string
  key?: string
  args?: Record<string, unknown>
  result?: unknown
}

type DrawerTab = 'result' | 'process' | 'trace'

const STATUS_LABEL: Record<string, string> = {
  running: 'exec.status.running',
  completed: 'exec.status.completed',
  failed: 'exec.status.failed',
  skipped: 'exec.status.skipped',
}

function truncate(text: string, max = 240): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function summarize(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function estimatedTokens(result: unknown): number {
  // Placeholder until executions rows carry real token counts per tool.
  const text = typeof result === 'string' ? result : JSON.stringify(result ?? '')
  return Math.max(1, Math.round(text.length / 4))
}

function factValue(facts: Record<string, unknown> | undefined, key: string): unknown {
  return facts?.[key]
}

export function NodeRunDrawer({
  stageId,
  stageName,
  stageStatus,
  factKeys = [],
  facts,
  toolEvents = [],
  execution,
  onClose,
}: {
  stageId: string | null
  stageName?: string
  stageStatus?: string
  factKeys?: string[]
  facts?: Record<string, unknown>
  toolEvents?: DrawerToolEvent[]
  execution?: StageExecutionRow | null
  onClose: () => void
}) {
  const [tab, setTab] = useState<DrawerTab>('result')
  if (!stageId) return null

  const running = stageStatus === 'running'
  const resultKeys = factKeys.filter((key) => factValue(facts, key) !== undefined)

  const tabs: Array<{ id: DrawerTab; label: string; icon: ReactNode }> = [
    { id: 'result', label: t('drawer.tab.result'), icon: <ListChecks size={13} weight="bold" /> },
    { id: 'process', label: t('drawer.tab.process'), icon: <CaretRight size={13} weight="bold" /> },
    { id: 'trace', label: t('drawer.tab.trace'), icon: <ClockCounterClockwise size={13} weight="bold" /> },
  ]

  return (
    <aside className="node-drawer" data-testid="node-drawer" aria-label={t('drawer.aria')}>
      <header className="node-drawer-head">
        <div>
          <div className="node-drawer-stage">{stageName || stageId}</div>
          {stageStatus && <span className={`wf-badge wf-status-${stageStatus}`}>{stageStatus}</span>}
        </div>
        <button type="button" className="panel-toolbar-btn" aria-label={t('drawer.close')} onClick={onClose}>
          <X size={14} weight="bold" />
        </button>
      </header>

      <div className="node-drawer-tabs" role="tablist">
        {tabs.map((entry) => (
          <button
            key={entry.id}
            type="button"
            role="tab"
            aria-selected={tab === entry.id}
            className={tab === entry.id ? 'active' : ''}
            onClick={() => setTab(entry.id)}
          >
            {entry.icon}
            {entry.label}
          </button>
        ))}
      </div>

      <div className="node-drawer-body">
        {tab === 'result' && (
          running ? (
            <SkeletonRows rows={2} />
          ) : resultKeys.length === 0 ? (
            <Empty text={t('drawer.result.empty')} />
          ) : (
            <div className="node-drawer-facts">
              {resultKeys.map((key) => {
                const value = factValue(facts, key)
                const text = summarize(value)
                return (
                  <section key={key} className="node-drawer-fact">
                    <h4>{key}</h4>
                    <p>{truncate(text)}</p>
                    <details>
                      <summary>{t('drawer.result.raw')}</summary>
                      <pre>{text}</pre>
                    </details>
                  </section>
                )
              })}
            </div>
          )
        )}

        {tab === 'process' && (
          toolEvents.length === 0 ? (
            running ? <SkeletonRows rows={3} /> : <Empty text={t('drawer.process.empty')} />
          ) : (
            <ul className="node-drawer-events">
              {toolEvents.map((event, index) => {
                if (event.kind === 'call') {
                  const pending = !toolEvents.some(
                    (other, otherIndex) => other.kind === 'result' && other.tool === event.tool && otherIndex > index,
                  )
                  return (
                    <li key={`call-${index}`} className="node-drawer-event">
                      <span className="node-drawer-event-type">tool_call</span>
                      <span className="node-drawer-event-main">
                        {event.tool}
                        {event.args?.target ? <span className="muted"> · {String(event.args.target)}</span> : null}
                      </span>
                      {pending && running && <Skeleton className="skeleton" style={{ width: 64 }} />}
                    </li>
                  )
                }
                return (
                  <li key={`result-${index}`} className="node-drawer-event">
                    <span className="node-drawer-event-type">tool_result</span>
                    <span className="node-drawer-event-main">
                      {event.tool}
                      {event.key ? <span className="muted"> · {event.key}</span> : null}
                    </span>
                    <span className="node-drawer-event-meta">≈{estimatedTokens(event.result)} tokens</span>
                  </li>
                )
              })}
            </ul>
          )
        )}

        {tab === 'trace' && (
          running && !execution ? (
            <SkeletonRows rows={4} />
          ) : !execution ? (
            <Empty text={t('drawer.trace.empty')} icon={<MagnifyingGlass size={20} weight="duotone" />} />
          ) : (
            <dl className="node-drawer-trace">
              <div><dt>{t('drawer.trace.status')}</dt><dd><span className={`wf-badge wf-status-${execution.status}`}>{t(STATUS_LABEL[execution.status] ?? execution.status)}</span></dd></div>
              <div><dt>{t('drawer.trace.elapsed')}</dt><dd>{execution.elapsed_ms} ms</dd></div>
              <div><dt>{t('drawer.trace.toolCalls')}</dt><dd>{execution.tool_calls}</dd></div>
              <div><dt>{t('drawer.trace.llmCalls')}</dt><dd>{execution.llm_calls}</dd></div>
              <div><dt>{t('drawer.trace.tokens')}</dt><dd>{execution.tokens_in} / {execution.tokens_out}</dd></div>
              {execution.error && <div><dt>{t('drawer.trace.error')}</dt><dd className="text-danger">{execution.error}</dd></div>}
            </dl>
          )
        )}
      </div>
    </aside>
  )
}

function SkeletonRows({ rows }: { rows: number }) {
  return (
    <div className="node-drawer-skeleton" aria-busy="true">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="skeleton" style={{ width: index === rows - 1 ? '55%' : '90%' }} />
      ))}
    </div>
  )
}

function Empty({ text, icon }: { text: string; icon?: ReactNode }) {
  return (
    <div className="node-drawer-empty">
      {icon ?? <CircleNotch size={20} weight="duotone" />}
      <span>{text}</span>
    </div>
  )
}

export default NodeRunDrawer
