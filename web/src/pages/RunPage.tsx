import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import { CaretLeft, CaretRight, Crosshair, LinkSimple, ListMagnifyingGlass, PencilSimple, Plus, ShieldWarning, Trash } from '@phosphor-icons/react'
import { controlRun, cloneTemplate, exportReport, getRun, getRunExecutions, getSettings, getTemplate, getWorkflowState, listEvidence, listFindings, listLogs, listModels, listRuns, preflightRun, refineTemplate, sendConversationMessage, startConversationStream, startRun, stopRun, subscribeConversationEvents, subscribeRunEvents, type StageExecutionRow } from '../api'
import NodeRunDrawer, { type DrawerToolEvent } from '../components/NodeRunDrawer/NodeRunDrawer'
import { readHashParams } from '../hooks/useHashRoute'
import { ConversationDock } from '../components/ConversationDock'
import EvolutionPanel from '../components/EvolutionPanel'
import { Markdown } from '../components/Markdown'
import { RunReport } from '../components/RunReport'
import { RunScopeBadge } from '../components/RunScopeBadge'
import { RunTierBadge, type ToolTierEvent } from '../components/RunTierBadge'
import { isLlmMissingError, LlmRequiredNotice } from '../components/LlmRequiredNotice'
import { t, useLang } from '../i18n'
import { formatTime } from '../lib/format'
import { describeLog, logTypeLabel } from '../lib/logs'
import { RunDiffDialog } from '../components/RunDiffDialog'
import { RunReplayDialog } from '../components/RunReplayDialog'
import WorkflowGraph, { type WorkflowGraphHandle } from '../components/WorkflowGraph'
import { Button } from '../components/ui/Button'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'
import { EmptyState } from '../components/ui/EmptyState'
import { NameDialog } from '../components/ui/NameDialog'
import { Skeleton } from '../components/ui/Skeleton'
import { SegmentedControl } from '../components/ui/SegmentedControl'
import { Tag } from '../components/ui/Tag'
import { readLocal, writeLocal } from '../lib/storage'
import type { Evidence, EvolutionReport, Finding, LogLine, MissingTool, RunResult, RunSummary, RunWorkflowState, SelfCheckNote, Session, SessionKind, Template } from '../types'

type InspectorTab = 'stage' | 'findings' | 'evidence' | 'logs'

type AgentLogEntry =
  | { kind: 'stage'; stage: string }
  | { kind: 'text'; content: string }
  | { kind: 'tool'; tool: string; args: Record<string, unknown>; source?: string; stage?: string }
  | { kind: 'tool_result'; tool: string; key?: string; result: unknown }

interface StageOutput {
  tool: string
  key?: string
  result: unknown
}

interface Pending {
  tool: string
  args: Record<string, unknown>
}

function severityTone(value: string): 'danger' | 'warning' | 'success' | 'neutral' {
  if (value === 'critical' || value === 'high') return 'danger'
  if (value === 'medium') return 'warning'
  if (value === 'low') return 'success'
  return 'neutral'
}

function severityClass(value: string): string {
  if (value === 'critical' || value === 'high') return 'sev-high'
  if (value === 'medium') return 'sev-medium'
  if (value === 'low') return 'sev-low'
  return ''
}

// The scope verdict comes from the server's preflight so enforcement has a
// single source of truth; this only translates stable reason codes. A function
// so t() is evaluated at call time and follows language switches.
function scopeReasonText(): Record<string, string> {
  return {
    'target host is not in allowed scope': t('run.scope.reason.notInScope'),
    'target host could not be parsed': t('run.scope.reason.unparseable'),
    'target is restricted public infrastructure or a reserved range': t('run.scope.reason.restricted'),
  }
}

export default function RunPage({
  template: propTemplate,
  sessions,
  currentSessionId,
  projectName,
  onSelectSession,
  onCreateSession,
  onRenameSession,
  onDeleteSession,
  onUpdateSession,
  onOpenSettings,
  onActionComplete,
  onTemplateUpdated,
  onTemplateCreated,
  onRunComplete,
}: {
  template: Template | null
  sessions: Session[]
  currentSessionId: string
  onSelectSession: (id: string) => void
  onCreateSession: (kind: SessionKind, patch?: Partial<Session>) => Promise<Session>
  onRenameSession: (id: string, name: string) => Promise<void>
  onDeleteSession: (id: string) => Promise<void>
  onUpdateSession: (id: string, patch: Partial<Session>) => void
  onOpenSettings?: () => void
  projectName?: string
  pageTitle?: string
  onActionComplete: () => void
  onTemplateUpdated?: () => void
  onTemplateCreated?: (id: string) => void
  onRunComplete?: () => void
}) {
  const lang = useLang()
  const [models, setModels] = useState<string[]>([])
  const [efforts, setEfforts] = useState<string[]>([])
  const [streaming, setStreaming] = useState(false)
  const [streamingUser, setStreamingUser] = useState('')
  const [streamingText, setStreamingText] = useState('')
  const [streamingReport, setStreamingReport] = useState('')
  const [selfCheckByStep, setSelfCheckByStep] = useState<Record<string, SelfCheckNote[]>>({})
  const [evolution, setEvolution] = useState<EvolutionReport | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const [assistantStructured, setAssistantStructured] = useState<{
    tool?: string
    report?: string | null
    findings?: Finding[]
    stage_id?: string
    template_id?: string
  } | null>(null)
  const [lastRun, setLastRun] = useState<RunResult | null>(null)
  const [lastRunId, setLastRunId] = useState('')
  const [activeRunId, setActiveRunId] = useState('')
  const [runtimeState, setRuntimeState] = useState<RunWorkflowState | null>(null)
  const [controlMenu, setControlMenu] = useState<{ stageId: string; x: number; y: number } | null>(null)
  const [confirmAction, setConfirmAction] = useState<{ action: string; stageId?: string } | null>(null)
  const [refining, setRefining] = useState(false)
  const [refineResult, setRefineResult] = useState('')
  const [replayRunId, setReplayRunId] = useState('')
  const [diffOpen, setDiffOpen] = useState(false)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [reportBusy, setReportBusy] = useState('')
  const [dangerItems, setDangerItems] = useState<{ tool: string; category: string; rule_id: string; action: string; reason: string }[]>([])
  const [missingTools, setMissingTools] = useState<MissingTool[]>([])
  const [toolTiers, setToolTiers] = useState<{ real: number; sim: number; items: ToolTierEvent[] }>({ real: 0, sim: 0, items: [] })
  const [dangerBusy, setDangerBusy] = useState(false)
  const [dangerAllowances, setDangerAllowances] = useState<string[]>([])
  const [error, setError] = useState('')
  const [llmMissing, setLlmMissing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [runningRunId, setRunningRunId] = useState('')
  const [optimisticUser, setOptimisticUser] = useState('')
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('stage')
  const [findings, setFindings] = useState<Finding[]>([])
  const [evidence, setEvidence] = useState<Evidence[]>([])
  const [logs, setLogs] = useState<LogLine[]>([])
  const [currentStageId, setCurrentStageId] = useState<string | null>(null)
  const [stageOutputs, setStageOutputs] = useState<Record<string, StageOutput[]>>({})
  const [agentLog, setAgentLog] = useState<AgentLogEntry[]>([])
  const [agentText, setAgentText] = useState('')
  const agentTextRef = useRef('')
  const [runElapsed, setRunElapsed] = useState(0)
  const [drawerStageId, setDrawerStageId] = useState<string | null>(null)
  const [highlightStageId, setHighlightStageId] = useState<string | null>(null)
  const [runStageDone, setRunStageDone] = useState(0)
  const graphRef = useRef<WorkflowGraphHandle | null>(null)
  const [stageExecutions, setStageExecutions] = useState<Record<string, StageExecutionRow>>({})
  const [renaming, setRenaming] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null)
  const [sessionsOpen, setSessionsOpen] = useState(() => readLocal('lattice.ui.runSessions', '1') !== '0')
  const [outputsOpen, setOutputsOpen] = useState(() => readLocal('lattice.ui.runOutputs', '1') !== '0')
  const [sessionsWidth, setSessionsWidth] = useState(() => Number(readLocal('lattice.ui.runSessionsWidth', '')) || 280)
  const sessionsWidthRef = useRef(sessionsWidth)

  useEffect(() => {
    sessionsWidthRef.current = sessionsWidth
  }, [sessionsWidth])

  useEffect(() => {
    getSettings()
      .then((s) => setLlmMissing(!s.has_api_key))
      .catch(() => setLlmMissing(false))
  }, [])

  // 模板卡“运行”按钮经 #/run?template=<id> 预选模板。App 级的 activeTemplate
  // 归导入向导工作流所有，这里用本地 override 承接预选，可一键退回。
  const [templateOverride, setTemplateOverride] = useState<Template | null>(null)
  const template = templateOverride ?? propTemplate

  useEffect(() => {
    let alive = true
    function applyTemplateParam() {
      const params = readHashParams()
      const id = params.get('template')
      if (id) {
        getTemplate(id)
          .then((tpl) => {
            if (alive) setTemplateOverride(tpl)
          })
          .catch(() => {})
      }
      // 模板卡“改进建议”入口经 #/run?template=<id>&run=<run_id> 深链到对应报告。
      const runId = params.get('run')
      if (runId) {
        getRun(runId)
          .then((run) => {
            if (!alive) return
            setLastRun(run as unknown as RunResult)
            setLastRunId(runId)
            setActiveRunId(runId)
            setEvolution(run.evolution ?? null)
            // 与流式完成路径一致：历史 run 也要恢复运行态（节点状态色、
            // 抽屉追踪 Tab 与事件↔画布联动）。
            refreshWorkflowState(runId)
            getRunExecutions(runId)
              .then(({ executions }) => {
                if (alive) setStageExecutions(Object.fromEntries(executions.map((row) => [row.stage_id, row])))
              })
              .catch(() => {
                if (alive) setStageExecutions({})
              })
            loadOutputs(runId)
            if (run.template_id) {
              getTemplate(run.template_id)
                .then((tpl) => {
                  if (alive) setTemplateOverride(tpl)
                })
                .catch(() => {})
            }
          })
          .catch(() => {})
      }
    }
    applyTemplateParam()
    window.addEventListener('hashchange', applyTemplateParam)
    return () => {
      alive = false
      window.removeEventListener('hashchange', applyTemplateParam)
    }
  }, [])

  const [cloneBusy, setCloneBusy] = useState(false)
  const [cloneMessage, setCloneMessage] = useState('')
  // 报告页的“克隆为自定义模板”：克隆后直接预选副本，方便接着二次运行
  async function cloneAsCustom() {
    if (!template) return
    setCloneBusy(true)
    setCloneMessage('')
    try {
      const result = await cloneTemplate(template.id)
      const clone = await getTemplate(result.id).catch(() => null)
      if (clone) setTemplateOverride(clone)
      setCloneMessage(`${t('tpl.run.cloned')} ${result.id}`)
    } catch (e) {
      setCloneMessage(String(e))
    } finally {
      setCloneBusy(false)
    }
  }

  function startSessionsResize(event: ReactMouseEvent) {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = sessionsWidthRef.current
    function onMove(ev: MouseEvent) {
      const next = Math.min(Math.max(startWidth + (ev.clientX - startX), 200), 420)
      sessionsWidthRef.current = next
      setSessionsWidth(next)
    }
    function onUp() {
      writeLocal('lattice.ui.runSessionsWidth', String(sessionsWidthRef.current))
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  function toggleSessions() {
    setSessionsOpen((value) => {
      writeLocal('lattice.ui.runSessions', value ? '0' : '1')
      return !value
    })
  }

  function toggleOutputs() {
    setOutputsOpen((value) => {
      writeLocal('lattice.ui.runOutputs', value ? '0' : '1')
      return !value
    })
  }
  const endRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const skipDangerPreflightRef = useRef(false)
  const scopeConfirmedRef = useRef(false)
  const [scopePrompt, setScopePrompt] = useState<{ target: string; reason: string } | null>(null)
  const autoScrollRef = useRef(true)

  const current = sessions.find((s) => s.id === currentSessionId) ?? null
  const assistantSessions = sessions.filter((s) => s.kind === 'assistant')
  const taskSessions = sessions.filter((s) => s.kind === 'task')

  function loadOutputs(runId?: string) {
    listRuns().then((r) => {
      setRuns(r.runs)
      const target =
        runId ||
        [...r.runs].sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')))[0]?.id ||
        ''
      if (!target) return
      setActiveRunId(target)
      listFindings().then((res) => setFindings(res.findings.filter((f) => f.run_id === target)))
      listEvidence().then((res) => setEvidence(res.evidence.filter((e) => e.run_id === target)))
      listLogs().then((res) => setLogs(res.logs.filter((l) => l.run_id === target)))
    })
  }

  function refreshWorkflowState(runId: string) {
    getWorkflowState(runId)
      .then(setRuntimeState)
      .catch(() => setRuntimeState(null))
  }

  function openControlMenu(stageId: string, event: React.MouseEvent) {
    setControlMenu({ stageId, x: event.clientX, y: event.clientY })
  }

  function requestControl(action: string, stageId?: string) {
    setControlMenu(null)
    setConfirmAction({ action, stageId })
  }

  function doControl() {
    if (!confirmAction || !lastRunId) return
    const { action, stageId } = confirmAction
    controlRun(lastRunId, action, stageId, true)
      .then(() => refreshWorkflowState(lastRunId))
      .catch((caught) => setError(String(caught)))
      .finally(() => setConfirmAction(null))
  }

  function applySuggestions() {
    if (!template || !evolution?.suggestions?.length) return
    setRefining(true)
    setRefineResult('')
    refineTemplate(template.id, evolution.suggestions)
      .then((r) => setRefineResult(t('run.refine.applied').replace('{version}', String(r.new_version))))
      .catch((caught) => setError(String(caught)))
      .finally(() => setRefining(false))
  }

  function appendAgentText(chunk: string) {
    agentTextRef.current += chunk
    setAgentText(agentTextRef.current)
  }

  function flushAgentText() {
    const text = agentTextRef.current
    if (!text) return
    setAgentLog((prev) => [...prev, { kind: 'text', content: text }])
    agentTextRef.current = ''
    setAgentText('')
  }

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
    loadOutputs()
  }, [template?.id])

  useEffect(() => {
    setCurrentStageId(template?.start ?? template?.stages?.[0]?.id ?? null)
    setStageOutputs({})
  }, [template])

  useEffect(() => {
    if (!autoScrollRef.current) return
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [sessions, lastRun, agentText, agentLog])

  useEffect(() => {
    if (!optimisticUser) return
    const echoed = current?.messages.some((m) => m.role === 'user' && m.content === optimisticUser)
    if (echoed) setOptimisticUser('')
  }, [current?.messages, optimisticUser])

  useEffect(() => {
    if (!(busy && current?.kind === 'task')) return
    setRunElapsed(0)
    const id = window.setInterval(() => setRunElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(id)
  }, [busy, current?.kind])

  async function submit(text: string, kind: SessionKind) {
    if (!current) return
    if (kind === 'task') {
      await maybeRunTask(current)
    } else {
      await sendAssistant(current, text)
    }
  }

  function applyAssistantStructured(event: { type: string; data?: Record<string, unknown> }) {
    if (event.type !== 'tool_result') return
    const data = event.data as { tool?: string; result?: Record<string, unknown> } | undefined
    const payload = data?.result as Record<string, unknown> | undefined
    if (!data?.tool || !payload) return
    if (data.tool === 'try_tool') {
      setAssistantStructured({
        tool: 'try_tool',
        report: payload.report as string | null,
        findings: payload.findings as Finding[] | undefined,
      })
    } else if (data.tool === 'bind_tool') {
      setAssistantStructured({
        tool: 'bind_tool',
        stage_id: payload.stage_id as string | undefined,
        template_id: payload.template_id as string | undefined,
      })
    }
  }

  async function sendAssistant(conv: Session, text: string) {
    setError('')
    setBusy(true)
    setStreaming(true)
    setStreamingUser(text)
    setStreamingText('')
    setAssistantStructured(null)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const { job_id } = await startConversationStream(conv.id, text, undefined, controller.signal)
      const result = await subscribeConversationEvents(
        conv.id,
        job_id,
        (event) => {
          if (event.type === 'content_delta') setStreamingText((prev) => prev + (event.content ?? ''))
          applyAssistantStructured(event)
        },
        controller.signal,
      )
      if (result.pending) setPending(result.pending)
      onActionComplete()
    } catch (caught) {
      setError(controller.signal.aborted ? t('run.cancelled') : String(caught))
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setStreaming(false)
      setStreamingUser('')
      setStreamingText('')
      setBusy(false)
    }
  }

  async function confirmPending() {
    if (!current || !pending) return
    const confirm = pending
    setPending(null)
    setBusy(true)
    setError('')
    setAssistantStructured(null)
    try {
      const result = await sendConversationMessage(current.id, '', { tool: confirm.tool, args: confirm.args })
      for (const event of result.events ?? []) applyAssistantStructured(event)
      if (confirm.tool === 'save_template') {
        const templateId = String(confirm.args.template_id ?? '')
        if (templateId && onTemplateCreated) onTemplateCreated(templateId)
      }
      onActionComplete()
    } catch (caught) {
      setError(String(caught))
    } finally {
      setBusy(false)
    }
  }

  async function downloadReport(format: 'md' | 'html' | 'json') {
    if (!lastRunId) return
    setReportBusy(format)
    try {
      const text = await exportReport(lastRunId, format)
      const blob = new Blob([text], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${lastRunId}.${format}`
      a.click()
      URL.revokeObjectURL(url)
    } catch (caught) {
      setError(String(caught))
    } finally {
      setReportBusy('')
    }
  }

  async function maybeRunTask(conv: Session) {
    if (template && !scopeConfirmedRef.current) {
      try {
        const preflight = await preflightRun(template, conv.target ?? '')
        const scope = preflight.scope
        if (scope && !scope.ok) {
          setScopePrompt({
            target: conv.target ?? '',
            reason: (scope.reason && scopeReasonText()[scope.reason]) || scope.reason || t('run.scope.notAuthorized'),
          })
          return
        }
      } catch {
        // preflight unavailable: continue; the server still enforces scope per tool call
      }
    }
    scopeConfirmedRef.current = false
    await runTask(conv)
  }

  function confirmScopeRun() {
    scopeConfirmedRef.current = true
    setScopePrompt(null)
    if (current) void runTask(current)
  }

  function cancelScopeRun() {
    scopeConfirmedRef.current = false
    setScopePrompt(null)
  }

  async function confirmDangerPreflight() {
    const allowances = dangerItems.map((item) => item.tool)
    setDangerAllowances(allowances)
    setDangerItems([])
    setDangerBusy(true)
    if (current) {
      await runTask(current)
    }
    setDangerBusy(false)
  }

  async function startExample() {
    setError('')
    try {
      const settings = await getSettings()
      if (!settings.has_api_key) {
        setLlmMissing(true)
        return
      }
      if (!template) {
        setError(t('run.error.noTemplate'))
        return
      }
      const conv = await onCreateSession('task', {
        name: t('run.example.sessionName'),
        target: 'example.com',
      })
      onSelectSession(conv.id)
      await maybeRunTask(conv)
    } catch (caught) {
      setError(String(caught))
    }
  }

  async function runTask(conv: Session) {
    if (!template) return
    let completedRunId = ''
    setError('')
    setMissingTools([])
    setBusy(true)
    setStreamingReport('')
    setSelfCheckByStep({})
    setEvolution(null)
    setAgentLog([])
    setToolTiers({ real: 0, sim: 0, items: [] })
    agentTextRef.current = ''
    setAgentText('')
    setOptimisticUser(conv.target ?? '')
    autoScrollRef.current = true
    const controller = new AbortController()
    abortRef.current = controller
    try {
      if (skipDangerPreflightRef.current) {
        skipDangerPreflightRef.current = false
      } else {
        const preflight = await preflightRun(template, conv.target ?? '')
        setMissingTools(preflight.missing_tools ?? [])
        const blocking = preflight.items.filter((item) => item.action !== 'allow')
        if (blocking.length > 0) {
          skipDangerPreflightRef.current = true
          setDangerItems(blocking)
          return
        }
      }
      const { id } = await startRun(
        template,
        conv.target ?? '',
        conv.autonomous,
        conv.self_check ?? false,
        dangerAllowances,
        conv.id,
        controller.signal,
      )
      setRunningRunId(id)
      setRunStageDone(0)
      const response = await subscribeRunEvents(
        id,
        (event) => {
          if (event.type === 'self_check') {
            const label = event.step?.label ?? ''
            const stage = event.step?.stage ?? label
            if (label) {
              setSelfCheckByStep((prev) => ({
                ...prev,
                [label]: event.notes ?? [],
                [`stage ${stage}`]: event.notes ?? [],
              }))
            }
          }
          if (event.type === 'evolution_complete') {
            setEvolution(event.evolution ?? null)
          }
          if (event.type === 'report_delta') {
            setStreamingReport((prev) => prev + (event.content ?? ''))
          }
          if (event.type === 'content_delta') {
            appendAgentText(event.content ?? '')
          }
          if (event.type === 'agent_message') {
            const data = event.data as { content?: string; tool_calls?: unknown[]; stage?: string } | undefined
            if (!agentTextRef.current && data?.content) {
              agentTextRef.current = data.content
              setAgentText(data.content)
            } else {
              flushAgentText()
            }
          }
          if (event.type === 'tool_tier') {
            const data = event.data as { tool?: string; tier?: string; reason?: string } | undefined
            if (data?.tool && (data.tier === 'real' || data.tier === 'sim')) {
              setToolTiers((prev) => ({
                real: prev.real + (data.tier === 'real' ? 1 : 0),
                sim: prev.sim + (data.tier === 'sim' ? 1 : 0),
                items: [...prev.items, { tool: data.tool!, tier: data.tier!, reason: data.reason ?? '' }],
              }))
            }
          }
          if (event.type === 'tool_call') {
            flushAgentText()
            const data = event.data as { tool?: string; args?: Record<string, unknown>; source?: string; stage?: string } | undefined
            setAgentLog((prev) => [...prev, { kind: 'tool', tool: data?.tool ?? '', args: data?.args ?? {}, source: data?.source, stage: data?.stage }])
          }
          if (event.type === 'stage_started') {
            const stage = event.data?.stage as string | undefined
            flushAgentText()
            if (stage) setCurrentStageId(stage)
          }
          if (event.type === 'stage_finished') {
            setRunStageDone((value) => value + 1)
          }
          if (event.type === 'tool_result') {
            flushAgentText()
            const stage = event.data?.stage as string | undefined
            const tool = event.data?.tool as string | undefined
            const key = event.data?.key as string | undefined
            const result = event.data?.result
            if (stage && tool) {
              setStageOutputs((previous) => ({
                ...previous,
                [stage]: [...(previous[stage] ?? []), { tool, key, result }],
              }))
            }
            setAgentLog((prev) => [...prev, { kind: 'tool_result', tool: tool ?? '', key, result }])
          }
        },
        controller.signal,
      )
      setLastRun(response)
      setLastRunId(id)
      completedRunId = id
      refreshWorkflowState(id)
      getRunExecutions(id)
        .then(({ executions }) => {
          setStageExecutions(Object.fromEntries(executions.map((row) => [row.stage_id, row])))
        })
        .catch(() => setStageExecutions({}))
      setEvolution(response.evolution ?? null)
      setStreamingReport('')
      onUpdateSession(conv.id, { last_run_id: id })
      onRunComplete?.()
    } catch (caught) {
      setError(controller.signal.aborted ? t('run.error.paused') : String(caught))
      setStreamingReport('')
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setBusy(false)
      setRunningRunId('')
      loadOutputs(completedRunId)
      onActionComplete()
    }
  }

  function handleStop() {
    if (runningRunId) {
      void stopRun(runningRunId).catch(() => {})
    }
    abortRef.current?.abort()
  }

  function renderInspector() {
    if (inspectorTab === 'stage') {
      const stages = template?.stages ?? []
      const currentStage = stages.find((s) => s.id === currentStageId) ?? stages[0] ?? null
      const currentIndex = currentStage ? stages.findIndex((s) => s.id === currentStage.id) + 1 : 0
      const kind: 'start' | 'end' | 'normal' = !currentStage
        ? 'normal'
        : currentIndex === 1
          ? 'start'
          : currentIndex === stages.length
            ? 'end'
            : 'normal'
      const tag = !currentStage ? '' : currentIndex === 1 ? t('run.stage.tagStart') : currentIndex === stages.length ? t('run.stage.tagEnd') : ''
      const outputs = currentStage ? stageOutputs[currentStage.id] ?? [] : []
      return (
        <div className="run-stage-view">
          {currentStage ? (
            <div className={`stage-node run-stage-card ${kind}`}>
              <span className="stage-node-index">{currentIndex}</span>
              <div className="stage-node-title">{currentStage.name}</div>
              {tag && <span className="stage-node-tag">{tag}</span>}
            </div>
          ) : (
            <div className="run-output-empty">{t('run.stage.empty')}</div>
          )}
          <div className="run-panel-title" style={{ marginTop: 12 }}>
            {t('run.stage.outputs')}
          </div>
          {outputs.length === 0 ? (
            <p className="muted run-stage-outputs-empty">{t('run.stage.outputsEmpty')}</p>
          ) : (
            <div className="output-list">
              {outputs.map((output, index) => (
                <div key={`${output.tool}-${index}`} className="stage-output">
                  <div className="stage-output-head">
                    <Tag>{output.tool}</Tag>
                    {output.key && <span className="muted">{output.key}</span>}
                  </div>
                  <pre className="stage-output-data">{JSON.stringify(output.result, null, 2)}</pre>
                </div>
              ))}
            </div>
          )}
          {(selfCheckByStep[`stage ${currentStage?.id}`] ?? []).length > 0 && (
            <div className="self-check-notes">
              <div className="run-panel-title">{t('composer.selfcheck')}</div>
              {(selfCheckByStep[`stage ${currentStage?.id}`] ?? []).map((note, index) => (
                <div key={index} className={`self-check-note ${note.kind}`}>
                  {note.text}
                </div>
              ))}
            </div>
          )}
          {template?.summary && (
            <pre className="run-summary">{template.description_i18n?.[lang] ?? template.summary}</pre>
          )}
        </div>
      )
    }

    if (inspectorTab === 'findings') {
      if (findings.length === 0) return <div className="run-output-empty">{t('run.findings.empty')}</div>
      return (
        <div className="output-list">
          {findings.map((finding) => (
            <div key={finding.id} className={`finding-card sev-square ${severityClass(finding.severity)}`}>
              <div className="finding-head">
                <ShieldWarning size={15} weight="bold" />
                <div className="finding-title">{finding.title}</div>
              </div>
              {finding.target && <div className="finding-target">{finding.target}</div>}
              <div className="card-tags">
                <Tag tone={severityTone(finding.severity)}>{finding.severity}</Tag>
                <Tag>{finding.status}</Tag>
                {(finding.evidence_ids ?? []).length > 0 && (
                  <Tag>
                    <LinkSimple size={11} weight="bold" /> {finding.evidence_ids!.length}
                  </Tag>
                )}
              </div>
            </div>
          ))}
        </div>
      )
    }

    if (inspectorTab === 'evidence') {
      if (evidence.length === 0) return <div className="run-output-empty">{t('run.evidence.empty')}</div>
      return (
        <div className="output-list">
          {evidence.map((ev) => (
            <div key={ev.id} className="output-evidence">
              <div className="output-evidence-head">
                <Tag>{ev.tool}</Tag>
                <span className="muted">{ev.stage_id}</span>
              </div>
              <pre className="output-evidence-data">{JSON.stringify(ev.result ?? ev.args, null, 2)}</pre>
            </div>
          ))}
        </div>
      )
    }

    if (logs.length === 0) return <div className="run-output-empty">{t('run.logs.empty')}</div>
    return (
      <div className="output-list">
        {logs.map((log, index) => {
          const stage = log.data?.stage as string | undefined
          // canvas linkage: click/hover on an event row focuses its stage node
          const focusStage = () => {
            if (!stage) return
            setHighlightStageId(stage)
            graphRef.current?.focusStage(stage)
          }
          // pending tool_result: a tool_call whose result never streamed in
          const pendingResult =
            log.type === 'tool_call' &&
            !logs.some((other) => other.type === 'tool_result' && other.data?.stage === stage && other.data?.tool === log.data?.tool && (other.seq ?? 0) > (log.seq ?? 0))
          return (
            <details key={`${log.run_id}-${log.seq ?? index}`} className="output-log">
              <summary
                onClick={() => focusStage()}
                onMouseEnter={() => stage && setHighlightStageId(stage)}
                style={{ cursor: stage ? 'pointer' : undefined }}
              >
                <ListMagnifyingGlass size={14} weight="bold" />
                <span className="mono-area output-log-type">{logTypeLabel(log.type)}</span>
                <span className="output-log-summary">{describeLog(log)}</span>
                <span className="muted output-log-time">{formatTime(log.created_at ?? log.run_id)}</span>
                {pendingResult && <Skeleton className="skeleton" style={{ width: 56, marginLeft: 'auto' }} />}
              </summary>
              <pre className="output-log-data">{JSON.stringify(log.data, null, 2)}</pre>
            </details>
          )
        })}
      </div>
    )
  }

  return (
    <div className="page">
      <div className="run-layout run-layout-3col">
        {sessionsOpen ? (
          <aside className="run-sessions" style={{ width: sessionsWidth }}>
            <div className="run-panel-header">
              <span className="run-panel-title">{projectName ?? t('module.project')}</span>
              <div className="card-actions">
                <span className="muted">{sessions.length}</span>
                <button type="button" className="panel-toolbar-btn" aria-label={t('run.sessions.hide')} title={t('run.sessions.hide')} onClick={toggleSessions}>
                  <CaretLeft size={14} weight="bold" />
                </button>
              </div>
            </div>
            <div className="session-list">
              <div className="session-group-label">{t('session.assistant')}</div>
              {assistantSessions.length === 0 ? (
                <div className="run-output-empty">{t('run.sessions.emptyAssistant')}</div>
              ) : (
                assistantSessions.map((s) => (
                  <SessionRow key={s.id} session={s} active={s.id === currentSessionId} onSelect={onSelectSession} onRename={setRenaming} onDelete={setConfirmingDelete} />
                ))
              )}
              <div className="session-group-label" style={{ marginTop: 'var(--space-3)' }}>
                {t('run.sessions.tasks')}
              </div>
              {taskSessions.length === 0 ? (
                <div className="run-output-empty">{t('run.sessions.emptyTasks')}</div>
              ) : (
                taskSessions.map((s) => (
                  <SessionRow key={s.id} session={s} active={s.id === currentSessionId} onSelect={onSelectSession} onRename={setRenaming} onDelete={setConfirmingDelete} />
                ))
              )}
            </div>
            <div className="session-actions">
              <Button size="sm" variant="secondary" icon={<Plus size={14} weight="bold" />} onClick={() => void onCreateSession('assistant')}>
                {t('run.sessions.assistant')}
              </Button>
              <Button size="sm" variant="secondary" icon={<Plus size={14} weight="bold" />} onClick={() => void onCreateSession('task')}>
                {t('session.task')}
              </Button>
            </div>
            <div className="run-sessions-resizer" role="separator" aria-orientation="vertical" onMouseDown={startSessionsResize} title={t('run.sessions.resize')} />
          </aside>
        ) : (
          <div className="run-panel-collapsed">
            <button type="button" className="panel-toolbar-btn" aria-label={t('run.sessions.show')} title={t('run.sessions.show')} onClick={toggleSessions}>
              <CaretRight size={14} weight="bold" />
            </button>
            <span className="run-panel-collapsed-label">{t('panel.sessions')}</span>
          </div>
        )}

        <section className="run-main">
          {templateOverride && (
            <div className="run-template-override">
              <span>
                {t('tpl.run.override')} <strong>{templateOverride.id}</strong>
              </span>
              <Button size="sm" variant="ghost" onClick={() => setTemplateOverride(null)}>
                {t('tpl.run.exitOverride')}
              </Button>
            </div>
          )}
          <RunScopeBadge />
          <RunTierBadge real={toolTiers.real} sim={toolTiers.sim} items={toolTiers.items} />
          {(llmMissing || isLlmMissingError(error)) && <LlmRequiredNotice onConfigure={onOpenSettings} />}
          {error && !isLlmMissingError(error) && <div className="run-error">{error}</div>}
          {current?.kind === 'task' && busy && (
            <div className="run-status">{t('run.status.elapsed').replace('{seconds}', String(runElapsed))}</div>
          )}
          {current?.kind === 'task' && lastRun && (
            <>
              <RunReport
                run={{ ...lastRun, evolution: evolution ?? lastRun.evolution }}
                templateId={template?.id}
                workflowTemplate={template}
                onTemplateUpdated={onTemplateUpdated}
              />
              <div className="card-actions" style={{ marginTop: 8 }}>
                <Button size="sm" loading={reportBusy === 'md'} onClick={() => downloadReport('md')}>{t('run.export.markdown')}</Button>
                <Button size="sm" loading={reportBusy === 'html'} onClick={() => downloadReport('html')}>{t('run.export.html')}</Button>
                <Button size="sm" loading={reportBusy === 'json'} onClick={() => downloadReport('json')}>{t('run.export.json')}</Button>
                <Button size="sm" onClick={() => setReplayRunId(lastRunId)}>{t('run.replay')}</Button>
                <Button size="sm" onClick={() => setDiffOpen(true)}>{t('run.diff')}</Button>
                {template && (
                  <Button size="sm" loading={cloneBusy} onClick={() => void cloneAsCustom()}>
                    {t('tpl.run.cloneAsCustom')}
                  </Button>
                )}
                {evolution?.suggestions && evolution.suggestions.length > 0 && (
                  <Button size="sm" loading={refining} onClick={applySuggestions}>
                    {t('run.applySuggestions')}
                  </Button>
                )}
              </div>
              {refineResult && <p className="text-success" style={{ marginTop: 8 }}>{refineResult}</p>}
              {cloneMessage && <p className="text-success" style={{ marginTop: 8 }}>{cloneMessage}</p>}
              {template && (
                <EvolutionPanel
                  template={template}
                  evolution={evolution}
                  onApplied={(newVersion) => {
                    setRefineResult(t('run.refine.applied').replace('{version}', String(newVersion)))
                    getTemplate(template.id)
                      .then(setTemplateOverride)
                      .catch(() => {})
                  }}
                />
              )}
              {template && (
                <div className="wf-runtime-block">
                  <div className="wf-runtime-header">
                    <span className="run-panel-title">{t('run.dag.title')}</span>
                    <span className="muted">{t('run.dag.hint').replace('{id}', lastRunId.slice(0, 8))}</span>
                    <Button size="sm" variant="ghost" onClick={() => refreshWorkflowState(lastRunId)}>
                      {t('run.dag.refresh')}
                    </Button>
                  </div>
                  <WorkflowGraph
                    ref={graphRef}
                    template={template}
                    runtime={runtimeState}
                    highlightStageId={highlightStageId}
                    onNodeClick={(stageId) => setDrawerStageId(stageId)}
                    onNodeContextMenu={(stageId, event) => openControlMenu(stageId, event)}
                  />
                  {controlMenu && (
                    <div className="wf-context-menu" style={{ left: controlMenu.x, top: controlMenu.y }}>
                      <button type="button" onClick={() => requestControl('skip', controlMenu.stageId)}>{t('run.control.skip')}</button>
                      <button type="button" onClick={() => requestControl('jump', controlMenu.stageId)}>{t('run.control.jump')}</button>
                      <button type="button" onClick={() => requestControl('revisit', controlMenu.stageId)}>{t('run.control.revisit')}</button>
                      <button type="button" onClick={() => requestControl('resume')}>{t('run.control.resume')}</button>
                    </div>
                  )}
                  <ConfirmDialog
                    open={!!confirmAction}
                    title={t('run.control.confirmTitle')}
                    description={confirmAction ? t('run.control.confirmBody').replace('{stage}', String(confirmAction.stageId ?? '')).replace('{action}', confirmAction.action) : ''}
                    onConfirm={doControl}
                    onCancel={() => setConfirmAction(null)}
                  />
                </div>
              )}
            </>
          )}
          {current?.kind === 'task' && streamingReport && (
            <div className="run-report-stream">
              <Markdown content={streamingReport || '…'} />
            </div>
          )}
          <div className="run-chat" onScroll={(e) => {
            const el = e.currentTarget
            autoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
          }}>
            {!current ? (
              <EmptyState title={t('run.empty.noSession.title')} description={t('run.empty.noSession.desc')} icon={<Crosshair size={22} weight="duotone" />} />
            ) : current.kind === 'task' && (agentLog.length > 0 || agentText || optimisticUser || current.messages.length > 0) ? (
              <div className="chat-log task-chat">
                {current.messages.map((message, index) => (
                  <div key={`msg-${index}`} className={`msg ${message.role}`}>
                    <Markdown content={message.content} />
                  </div>
                ))}
                {optimisticUser && (
                  <div className="msg user">
                    <Markdown content={optimisticUser} />
                  </div>
                )}
                {agentLog.map((entry, index) => {
                  if (entry.kind === 'stage') {
                    return (
                      <div key={index} className="agent-stage">
                        <Tag>{entry.stage}</Tag>
                      </div>
                    )
                  }
                  if (entry.kind === 'text') {
                    return (
                      <div key={index} className="msg assistant">
                        <Markdown content={entry.content} />
                      </div>
                    )
                  }
                  if (entry.kind === 'tool') {
                    return (
                      <div key={index} className="msg assistant agent-tool">
                        <code>{entry.tool}</code> <span className="muted">{JSON.stringify(entry.args)}</span>
                      </div>
                    )
                  }
                  if (entry.kind === 'tool_result') {
                    return (
                      <details key={index} className="msg assistant agent-tool-result">
                        <summary>{t('run.toolResult').replace('{tool}', entry.tool)}</summary>
                        <pre>{JSON.stringify(entry.result, null, 2)}</pre>
                      </details>
                    )
                  }
                  return null
                })}
                {agentText && (
                  <div className="msg assistant">
                    <Markdown content={agentText || '…'} />
                  </div>
                )}
              </div>
            ) : current.messages.length === 0 && !optimisticUser && !pending && !streaming ? (
              <EmptyState
                title={current.kind === 'assistant' ? t('run.empty.assistant.title') : t('run.empty.task.title')}
                description={current.kind === 'assistant' ? t('run.empty.assistant.desc') : t('run.empty.task.desc')}
                action={sessions.length === 0 ? (
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
                    {onOpenSettings && (
                      <Button size="sm" variant="secondary" onClick={onOpenSettings}>
                        {t('run.empty.configureLlm')}
                      </Button>
                    )}
                    <Button size="sm" variant="primary" onClick={() => void startExample()}>
                      {t('run.empty.runExample')}
                    </Button>
                  </div>
                ) : undefined}
                icon={<Crosshair size={22} weight="duotone" />}
              />
            ) : (
              <div className="chat-log">
                {current.messages.map((message, index) => (
                  <div key={index} className={`msg ${message.role}`}>
                    <Markdown content={message.content} />
                  </div>
                ))}
                {optimisticUser && (
                  <div className="msg user">
                    <Markdown content={optimisticUser} />
                  </div>
                )}
                {streamingUser && (
                  <div className="msg user">
                    <Markdown content={streamingUser} />
                  </div>
                )}
                {streaming && (
                  <div className="msg assistant">
                    <Markdown content={streamingText || '…'} />
                  </div>
                )}
              </div>
            )}
            {missingTools.length > 0 && (
              <div className="analysis-report">
                <h4>{t('run.missing.title')}</h4>
                {missingTools.map((item) => (
                  <div key={item.tool} className="field">
                    <span>
                      {item.tool} ·{' '}
                      {item.has_fallback ? t('run.missing.withFallback') : t('run.missing.noFallback')}
                      {item.install_mode === 'manual' ? t('run.missing.manual') : ''}
                    </span>
                    {item.hint && <p className="muted">{item.hint}</p>}
                  </div>
                ))}
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <Button size="sm" variant="primary" onClick={() => { window.location.hash = '/tools' }}>
                    {t('run.missing.install')}
                  </Button>
                  <Button size="sm" onClick={() => setMissingTools([])}>
                    {t('run.missing.dismiss')}
                  </Button>
                </div>
              </div>
            )}
            {dangerItems.length > 0 && (
              <div className="analysis-report">
                <h4>{t('run.danger.title')}</h4>
                {dangerItems.map((item) => (
                  <div key={item.tool} className="field">
                    <span>{item.tool} · {item.category}</span>
                    <p className="muted">{item.reason}</p>
                  </div>
                ))}
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <Button size="sm" variant="primary" loading={dangerBusy} onClick={confirmDangerPreflight}>
                    {t('dock.confirm')}
                  </Button>
                  <Button size="sm" onClick={() => { setDangerItems([]); skipDangerPreflightRef.current = false }}>
                    {t('common.cancel')}
                  </Button>
                </div>
              </div>
            )}
            {scopePrompt && (
              <div className="analysis-report">
                <h4>{t('run.scope.title')}</h4>
                <p className="muted">
                  {t('run.scope.body').replace('{target}', scopePrompt.target).replace('{reason}', scopePrompt.reason)}
                </p>
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <Button size="sm" variant="primary" onClick={confirmScopeRun}>
                    {t('dock.confirm')}
                  </Button>
                  <Button size="sm" onClick={cancelScopeRun}>
                    {t('common.cancel')}
                  </Button>
                </div>
              </div>
            )}
            {pending && (
              <div className="analysis-report">
                <h4>{pending.tool === 'save_template' ? t('run.pending.saveTemplate') : t('run.pending.title')}</h4>
                <p className="muted">
                  {pending.tool} {JSON.stringify(pending.args)}
                </p>
                <div style={{ display: 'flex', gap: 8 }}>
                  <Button size="sm" variant="primary" onClick={confirmPending} disabled={busy}>
                    {t('dock.confirm')}
                  </Button>
                  <Button size="sm" onClick={() => setPending(null)}>
                    {t('common.cancel')}
                  </Button>
                </div>
              </div>
            )}
            {assistantStructured && (
              <div className="assistant-structured-result" style={{ marginTop: 8 }}>
                {assistantStructured.report && <Markdown content={assistantStructured.report} />}
                {(assistantStructured.findings ?? []).map((finding) => (
                  <div key={finding.id} className="finding-row" style={{ marginTop: 6 }}>
                    <strong>{finding.severity}</strong> · {finding.title}
                    {finding.target && <span className="muted"> · {finding.target}</span>}
                  </div>
                ))}
                {assistantStructured.stage_id && (
                  <div className="text-success">
                    {t('run.bound').replace('{template}', String(assistantStructured.template_id ?? '')).replace('{stage}', String(assistantStructured.stage_id))}
                  </div>
                )}
              </div>
            )}
            <div ref={endRef} />
          </div>
          {current && (
            <ConversationDock
              session={current}
              busy={busy}
              models={models}
              efforts={efforts}
              onSubmit={submit}
              onUpdate={(patch) => onUpdateSession(current.id, patch)}
              onCancel={() => abortRef.current?.abort()}
              onStop={handleStop}
            />
          )}
          {busy && current?.kind === 'task' && (
            <div className="run-progress-bar" role="status" aria-label={t('runbar.aria')}>
              <span className="run-progress-count">
                {t('runbar.progress').replace('{done}', String(runStageDone)).replace('{total}', String(template?.stages.length ?? 0))}
              </span>
              <Button size="sm" variant="danger" onClick={handleStop}>
                {t('runbar.stop')}
              </Button>
            </div>
          )}
          {(() => {
            if (!drawerStageId) return null
            const drawerStage = template?.stages.find((s) => s.id === drawerStageId)
            const factKeys = (drawerStage?.tools ?? []).map((binding) => binding.key ?? binding.tool)
            const runtimeFacts = (runtimeState as (RunWorkflowState & { facts?: Record<string, unknown> }) | null)?.facts
            const historyEvents: DrawerToolEvent[] = logs
              .filter((line) => line.data?.stage === drawerStageId && (line.type === 'tool_call' || line.type === 'tool_result'))
              .map((line) => ({
                kind: line.type === 'tool_call' ? 'call' : 'result',
                tool: String(line.data?.tool ?? ''),
                key: line.data?.key as string | undefined,
                args: line.data?.args as Record<string, unknown> | undefined,
                result: line.data?.result,
              }))
            const liveEvents: DrawerToolEvent[] = agentLog
              .filter((entry): entry is Extract<AgentLogEntry, { kind: 'tool' | 'tool_result' }> =>
                entry.kind === 'tool' || entry.kind === 'tool_result')
              .filter((entry) => entry.kind === 'tool_result' || entry.stage === drawerStageId)
              .map((entry) => entry.kind === 'tool'
                ? { kind: 'call', tool: entry.tool, args: entry.args }
                : { kind: 'result', tool: entry.tool, key: entry.key, result: entry.result })
            return (
              <NodeRunDrawer
                stageId={drawerStageId}
                stageName={drawerStage?.name}
                stageStatus={runtimeState?.stage_status?.[drawerStageId]}
                factKeys={factKeys}
                facts={runtimeFacts}
                toolEvents={[...historyEvents, ...liveEvents]}
                execution={stageExecutions[drawerStageId] ?? null}
                onClose={() => setDrawerStageId(null)}
              />
            )
          })()}
        </section>

        {outputsOpen ? (
          <aside className="run-outputs">
            <div className="run-panel-header">
              <span className="run-panel-title">{t('run.outputs.title')}</span>
              <div className="card-actions">
                {activeRunId && <span className="muted">{t('run.runId').replace('{id}', activeRunId.slice(0, 8))}</span>}
                <button type="button" className="panel-toolbar-btn" aria-label={t('run.outputs.hide')} title={t('run.outputs.hide')} onClick={toggleOutputs}>
                  <CaretRight size={14} weight="bold" />
                </button>
              </div>
            </div>
            <div className="run-outputs-tabs">
              <SegmentedControl
                options={[
                  { value: 'stage', label: t('run.tab.stage') },
                  { value: 'findings', label: t('module.findings') },
                  { value: 'evidence', label: t('run.tab.evidence') },
                  { value: 'logs', label: t('run.tab.logs') },
                ]}
                value={inspectorTab}
                onChange={(value) => setInspectorTab(value)}
                ariaLabel={t('run.tabs.aria')}
              />
            </div>
            <div className="run-outputs-body">{renderInspector()}</div>
          </aside>
        ) : (
          <div className="run-panel-collapsed">
            <button type="button" className="panel-toolbar-btn" aria-label={t('run.outputs.show')} title={t('run.outputs.show')} onClick={toggleOutputs}>
              <CaretLeft size={14} weight="bold" />
            </button>
            <span className="run-panel-collapsed-label">{t('panel.outputs')}</span>
          </div>
        )}
      </div>

      <NameDialog
        open={!!renaming}
        title={t('run.session.rename')}
        initialValue={sessions.find((s) => s.id === renaming)?.name ?? ''}
        confirmLabel={t('common.save')}
        onConfirm={(name) => {
          if (renaming) void onRenameSession(renaming, name)
          setRenaming(null)
        }}
        onCancel={() => setRenaming(null)}
      />
      <ConfirmDialog
        open={!!confirmingDelete}
        title={t('run.session.deleteTitle')}
        description={t('run.session.deleteBody').replace('{name}', String(confirmingDelete && sessions.find((s) => s.id === confirmingDelete)?.name))}
        confirmLabel={t('run.session.delete')}
        danger
        onConfirm={() => {
          if (confirmingDelete) void onDeleteSession(confirmingDelete)
          setConfirmingDelete(null)
        }}
        onCancel={() => setConfirmingDelete(null)}
      />
      {replayRunId && <RunReplayDialog runId={replayRunId} onClose={() => setReplayRunId('')} />}
      {diffOpen && lastRunId && <RunDiffDialog runs={runs} headRunId={lastRunId} onClose={() => setDiffOpen(false)} />}
    </div>
  )
}

function SessionRow({
  session,
  active,
  onSelect,
  onRename,
  onDelete,
}: {
  session: Session
  active: boolean
  onSelect: (id: string) => void
  onRename: (id: string) => void
  onDelete: (id: string) => void
}) {
  return (
    <div className={`session-item ${active ? 'active' : ''}`}>
      <button className="session-item-main" onClick={() => onSelect(session.id)}>
        <span className={`session-kind ${session.kind}`}>{session.kind === 'assistant' ? t('run.sessions.assistant') : t('session.task')}</span>
        <span className="session-name">{session.name}</span>
      </button>
      {active && (
        <div className="session-item-actions">
          <button aria-label={t('run.session.rename')} onClick={() => onRename(session.id)}>
            <PencilSimple size={14} weight="bold" />
          </button>
          <button aria-label={t('run.session.deleteAria')} onClick={() => onDelete(session.id)}>
            <Trash size={14} weight="bold" />
          </button>
        </div>
      )}
    </div>
  )
}
