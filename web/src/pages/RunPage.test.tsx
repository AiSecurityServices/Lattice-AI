import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, expect, test, vi } from 'vitest'
import '../index.css'
import RunPage from './RunPage'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
})

vi.mock('../api', () => ({
  startRun: vi.fn(),
  subscribeRunEvents: vi.fn(),
  stopRun: vi.fn(),
  preflightRun: vi.fn().mockResolvedValue({ items: [], scope: { configured: false, ok: true, reason: '', restricted: false } }),
  getScope: vi.fn().mockResolvedValue({
    allow_domains: [],
    allow_ips: [],
    allow_cidrs: [],
    allow_ports: [80, 443],
    allow_url_prefixes: [],
  }),
  getSettings: vi.fn().mockResolvedValue({ provider: 'deepseek', base_url: '', model: '', api_key: '', has_api_key: true }),
  exportReport: vi.fn().mockResolvedValue(''),
  listModels: vi.fn().mockResolvedValue({ models: ['m'], efforts: ['off'] }),
  listEvidence: vi.fn().mockResolvedValue({
    evidence: [
      { id: 'e-old', run_id: 'r-old', stage_id: 'a', tool: 'old-tool', result: {} },
      { id: 'e-new', run_id: 'r1', stage_id: 'a', tool: 'new-tool', result: { value: 'hi' } },
    ],
  }),
  listFindings: vi.fn().mockResolvedValue({
    findings: [
      { id: 'f-old', run_id: 'r-old', title: 'Old Finding', severity: 'low', status: 'pending' },
      { id: 'f-new', run_id: 'r1', title: 'New Finding', severity: 'low', status: 'pending' },
    ],
  }),
  listLogs: vi.fn().mockResolvedValue({
    logs: [
      { run_id: 'r-old', seq: 1, type: 'old_event', data: {} },
      { run_id: 'r1', seq: 1, type: 'new_event', data: {} },
    ],
  }),
  listRuns: vi.fn().mockResolvedValue({
    runs: [
      { id: 'r-old', template_id: 't', target: 'old.example', created_at: '2026-08-28T21:00:00' },
      { id: 'r1', template_id: 't', target: 'new.example', created_at: '2026-08-28T20:00:00' },
    ],
  }),
  getWorkflowState: vi.fn().mockResolvedValue({ run_id: 'r1', current_stage: 'a', stage_status: { a: 'completed' }, facts: { a: { value: 'x' } } }),
  getRun: vi.fn().mockResolvedValue({
    id: 'r1',
    target: '127.0.0.1:9',
    template_id: 't1',
    kind: 'run',
    created_at: '2026-08-31T00:00:00',
    report: '# report',
    facts: { a: { value: 'x' } },
    events: [{ seq: 1, type: 'stage_finished', data: { stage: 'a', status: 'completed' } }],
    evolution: null,
  }),
  getTemplate: vi.fn().mockResolvedValue({
    id: 't1',
    name: 'demo',
    start: 'a',
    stages: [{ id: 'a', name: 'A', tools: [{ tool: 'echo', key: 'a' }] }],
    tools: [],
  }),
  getRunExecutions: vi.fn().mockResolvedValue({
    run_id: 'r1',
    executions: [
      { run_id: 'r1', stage_id: 'a', status: 'completed', started_at: '', finished_at: '', elapsed_ms: 120, tool_calls: 1, llm_calls: 0, tokens_in: 0, tokens_out: 0, error: '' },
    ],
  }),
  controlRun: vi.fn().mockResolvedValue({}),
  refineTemplate: vi.fn().mockResolvedValue({ new_version: 2, applied: [], rejected: [] }),
  sendConversationMessage: vi.fn(),
  startConversationStream: vi.fn(),
  subscribeConversationEvents: vi.fn(),
}))

test('shows agent process stream when task runs', async () => {
  const api = await import('../api')
  const template = {
    id: 't1',
    name: 'demo',
    start: 'a',
    stages: [{ id: 'a', name: 'a', tools: [{ tool: 'echo', key: 'out' }], skills: [] }],
    tools: [{ name: 'echo', description: 'e', runner: 'builtin' }],
    skills: [],
  }
  vi.mocked(api.startRun as any).mockResolvedValue({ id: 'r1' })
  vi.mocked(api.subscribeRunEvents as any).mockImplementation(
    (
      _runId: string,
      onEvent: (event: { type: string; content?: string; data?: Record<string, unknown> }) => void,
      _sig: AbortSignal,
    ) => {
      onEvent({ type: 'content_delta', content: 'hello' })
      onEvent({ type: 'tool_call', data: { tool: 'echo', args: { msg: 'hi' }, source: 'agent' } })
      onEvent({ type: 'tool_result', data: { stage: 'a', tool: 'echo', key: 'out', result: { value: 'hi' } } })
      onEvent({ type: 'report_delta', content: '# R' })
      return Promise.resolve({ id: 'r1', facts: {}, events: [], report: '# R', evolution: null })
    },
  )

  const session = {
    id: 'c1',
    name: 't',
    kind: 'task',
    template_id: 't1',
    model: '',
    reasoning_effort: 'off',
    project_id: 'default',
    created_at: '',
    updated_at: '',
    messages: [],
    target: 'x',
    autonomous: false,
    self_check: false,
    last_run_id: '',
  }
  render(
    <RunPage
      template={template as any}
      sessions={[session] as any}
      currentSessionId="c1"
      projectName="p"
      onSelectSession={vi.fn()}
      onCreateSession={vi.fn()}
      onRenameSession={vi.fn()}
      onDeleteSession={vi.fn()}
      onUpdateSession={vi.fn()}
      onActionComplete={vi.fn()}
    />,
  )

  fireEvent.click(await screen.findByRole('button', { name: /运行/ }))
  await waitFor(() => expect(screen.getByText('hello')).toBeTruthy())
  expect(screen.getAllByText(/echo/).length).toBeGreaterThan(0)

  // P2: after the run completes, the inspector tabs only show this run's data.
  await waitFor(() => {
    fireEvent.click(screen.getByRole('button', { name: '发现' }))
    expect(screen.getByText('New Finding')).toBeTruthy()
    expect(screen.queryByText('Old Finding')).toBeNull()
  })
  fireEvent.click(screen.getByRole('button', { name: '证据' }))
  expect(screen.getByText('new-tool')).toBeTruthy()
  expect(screen.queryByText('old-tool')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '时间线' }))
  expect(screen.getByText('new_event')).toBeTruthy()
  expect(screen.queryByText('old_event')).toBeNull()

  // P4: the run target is rendered as a user bubble alongside the agent stream
  await waitFor(() => expect(screen.getAllByText('x').length).toBeGreaterThan(0))

  // P3: runtime workflow state is fetched after the run completes
  await waitFor(() => expect(api.getWorkflowState).toHaveBeenCalledWith('r1'))
  // right-click a stage node opens the control menu; confirmed action calls controlRun
  fireEvent.contextMenu(screen.getAllByText('a')[0])
  fireEvent.click(screen.getByText('跳过'))
  fireEvent.click(screen.getByText('确认'))
  await waitFor(() => expect(api.controlRun).toHaveBeenCalledWith('r1', 'skip', 'a', true))
})

test('busy task shows pause control and stops the running run', async () => {
  const api = await import('../api')
  vi.mocked(api.startRun as any).mockResolvedValue({ id: 'r1' })
  vi.mocked(api.subscribeRunEvents as any).mockImplementation(() => new Promise(() => {}))
  vi.mocked(api.stopRun as any).mockResolvedValue({ stopped: 'r1' })

  const session = {
    id: 'c1',
    name: 't',
    kind: 'task',
    template_id: 't1',
    model: '',
    reasoning_effort: 'off',
    project_id: 'default',
    created_at: '',
    updated_at: '',
    messages: [],
    target: 'example.com',
    autonomous: false,
    self_check: false,
    last_run_id: '',
  }
  render(
    <RunPage
      template={{ id: 't1', name: 'demo', start: 'a', stages: [], tools: [] } as any}
      sessions={[session] as any}
      currentSessionId="c1"
      projectName="p"
      onSelectSession={vi.fn()}
      onCreateSession={vi.fn()}
      onRenameSession={vi.fn()}
      onDeleteSession={vi.fn()}
      onUpdateSession={vi.fn()}
      onActionComplete={vi.fn()}
    />,
  )

  fireEvent.click(await screen.findByRole('button', { name: /运行/ }))
  // target shows as a user bubble while the run is busy
  await waitFor(() => expect(screen.getAllByText('example.com').length).toBeGreaterThan(0))
  // floating run bar appears while busy and its Stop button also stops the run
  const runBar = await screen.findByRole('status', { name: /运行进度条/ })
  expect(runBar.textContent).toContain('0/0')  // this template stub has no stages
  fireEvent.click(screen.getByRole('button', { name: '停止' }))
  await waitFor(() => expect(api.stopRun).toHaveBeenCalledWith('r1'))
})

test('run completion marks assets and findings as updated', async () => {
  const api = await import('../api')
  vi.mocked(api.startRun as any).mockResolvedValue({ id: 'r1' })
  vi.mocked(api.subscribeRunEvents as any).mockResolvedValue({ id: 'r1', facts: {}, events: [], report: '# R', evolution: null })
  const onRunComplete = vi.fn()

  const session = {
    id: 'c1',
    name: 't',
    kind: 'task',
    template_id: 't1',
    model: '',
    reasoning_effort: 'off',
    project_id: 'default',
    created_at: '',
    updated_at: '',
    messages: [],
    target: 'example.com',
    autonomous: false,
    self_check: false,
    last_run_id: '',
  }
  render(
    <RunPage
      template={{ id: 't1', name: 'demo', start: 'a', stages: [], tools: [] } as any}
      sessions={[session] as any}
      currentSessionId="c1"
      projectName="p"
      onSelectSession={vi.fn()}
      onCreateSession={vi.fn()}
      onRenameSession={vi.fn()}
      onDeleteSession={vi.fn()}
      onUpdateSession={vi.fn()}
      onActionComplete={vi.fn()}
      onRunComplete={onRunComplete}
    />,
  )

  fireEvent.click(await screen.findByRole('button', { name: /运行/ }))
  await waitFor(() => expect(onRunComplete).toHaveBeenCalled())
})

test('out-of-scope target shows an inline confirmation instead of running', async () => {
  const api = await import('../api')
  vi.mocked(api.preflightRun as any).mockResolvedValue({
    items: [],
    scope: { configured: true, ok: false, reason: 'target host is not in allowed scope', restricted: false },
  })
  vi.mocked(api.startRun as any).mockResolvedValue({ id: 'r1' })
  vi.mocked(api.startRun as any).mockClear()
  vi.mocked(api.subscribeRunEvents as any).mockResolvedValue({ id: 'r1', facts: {}, events: [], report: '# R', evolution: null })

  const session = {
    id: 'c1',
    name: 't',
    kind: 'task',
    template_id: 't1',
    model: '',
    reasoning_effort: 'off',
    project_id: 'default',
    created_at: '',
    updated_at: '',
    messages: [],
    target: 'evil.example',
    autonomous: false,
    self_check: false,
    last_run_id: '',
  }
  render(
    <RunPage
      template={{ id: 't1', name: 'demo', start: 'a', stages: [], tools: [] } as any}
      sessions={[session] as any}
      currentSessionId="c1"
      projectName="p"
      onSelectSession={vi.fn()}
      onCreateSession={vi.fn()}
      onRenameSession={vi.fn()}
      onDeleteSession={vi.fn()}
      onUpdateSession={vi.fn()}
      onActionComplete={vi.fn()}
      onRunComplete={vi.fn()}
    />,
  )

  fireEvent.click(await screen.findByRole('button', { name: /运行/ }))
  await waitFor(() => expect(screen.getByText(/目标范围确认/)).toBeTruthy())
  expect(api.startRun).not.toHaveBeenCalled()

  fireEvent.click(screen.getByText('确认执行'))
  await waitFor(() => expect(api.startRun).toHaveBeenCalledWith(expect.anything(), 'evil.example', expect.anything(), expect.anything(), expect.anything(), 'c1', expect.anything()))
})

test('run button is not occluded: main column stacks above the outputs aside (E5)', async () => {
  const api = await import('../api')
  vi.mocked(api.listRuns).mockResolvedValue({ runs: [] })
  render(<RunPage template={null} sessions={[]} currentSessionId="" onSelectSession={() => {}} onCreateSession={vi.fn()} onRenameSession={vi.fn()} onDeleteSession={vi.fn()} onUpdateSession={() => {}} onActionComplete={() => {}} />)
  await waitFor(() => expect(document.querySelector('.run-main')).toBeTruthy())
  const main = getComputedStyle(document.querySelector('.run-main')!)
  const outputs = getComputedStyle(document.querySelector('.run-outputs')!)
  expect(main.position).toBe('relative')
  expect(main.zIndex).toBe('1')
  if (outputs.zIndex !== 'auto') expect(Number(outputs.zIndex)).toBeLessThan(Number(main.zIndex))
  // the outputs aside stays inside its own (lower) stacking context
  expect(outputs.position).toBe('relative')
})

test('run deep-link (#/run?run=) restores workflow state, executions and events', async () => {
  const api = await import('../api')
  vi.mocked(api.listRuns).mockResolvedValue({ runs: [] })
  window.location.hash = '#/run?run=r1'
  const session = {
    id: 'c1', name: 't', kind: 'task', template_id: 't1', model: '', reasoning_effort: 'off',
    project_id: 'default', created_at: '', updated_at: '', messages: [], target: '127.0.0.1:9',
    autonomous: false, self_check: false, last_run_id: '',
  }
  render(
    <RunPage
      template={null}
      sessions={[session] as any}
      currentSessionId="c1"
      onSelectSession={() => {}}
      onCreateSession={vi.fn()}
      onRenameSession={vi.fn()}
      onDeleteSession={vi.fn()}
      onUpdateSession={() => {}}
      onActionComplete={() => {}}
    />,
  )
  await waitFor(() => expect(api.getRun).toHaveBeenCalledWith('r1'))
  // 与流式完成路径一致：历史 run 恢复运行态与追踪数据
  await waitFor(() => expect(api.getWorkflowState).toHaveBeenCalledWith('r1'))
  await waitFor(() => expect(api.getRunExecutions).toHaveBeenCalledWith('r1'))
  // template_id 反查预选模板，报告区与运行态 DAG 出现（节点状态色/联动可用）
  await waitFor(() => expect(api.getTemplate).toHaveBeenCalledWith('t1'))
  expect(await screen.findByText('运行态 DAG')).toBeTruthy()
  window.location.hash = ''
})
