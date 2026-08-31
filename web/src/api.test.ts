import { afterEach, expect, it, vi } from 'vitest'
import {
  controlRun,
  getRunEvolution,
  getTemplateHistory,
  getWorkflowState,
  listAssets,
  listEvidence,
  listFindings,
  listRuns,
  refineTemplate,
  rollbackTemplate,
  startRun,
  stopRun,
} from './api'
import * as api from './api'

const fetchMock = vi.fn()

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

function okJson(data: unknown) {
  return { ok: true, json: async () => data, text: async () => '' }
}

it('builds workflow-state and control requests', async () => {
  fetchMock.mockResolvedValue(okJson({ run_id: 'r', current_stage: 'a', stage_status: {} }))
  vi.stubGlobal('fetch', fetchMock)

  await getWorkflowState('r')
  expect(String(fetchMock.mock.calls[0][0])).toContain('/api/runs/r/workflow-state')

  await controlRun('r', 'revisit', 'a', true)
  const [url, opts] = fetchMock.mock.calls[1]
  expect(String(url)).toContain('/api/runs/r/control')
  expect(JSON.parse(opts.body)).toEqual({ action: 'revisit', stage_id: 'a', confirm: true })
})

it('sends confirm=false by default for control', async () => {
  fetchMock.mockResolvedValue(okJson({}))
  vi.stubGlobal('fetch', fetchMock)
  await controlRun('r', 'skip', 'b')
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ action: 'skip', stage_id: 'b', confirm: false })
})

it('builds evolution, refine, history and rollback requests', async () => {
  fetchMock.mockResolvedValue(okJson({}))
  vi.stubGlobal('fetch', fetchMock)

  await getRunEvolution('r1')
  expect(String(fetchMock.mock.calls[0][0])).toContain('/api/runs/r1/evolution')

  await refineTemplate('t1', [{ type: 'add_depends_on', stage_id: 'b', depends_on: 'a' }], 'r1')
  const [refineUrl, refineOpts] = fetchMock.mock.calls[1]
  expect(String(refineUrl)).toContain('/api/templates/t1/refine')
  expect(JSON.parse(refineOpts.body)).toEqual({
    suggestions: [{ type: 'add_depends_on', stage_id: 'b', depends_on: 'a' }],
    run_id: 'r1',
  })

  await getTemplateHistory('t1')
  expect(String(fetchMock.mock.calls[2][0])).toContain('/api/templates/t1/history')

  await rollbackTemplate('t1', 3)
  const [rollbackUrl, rollbackOpts] = fetchMock.mock.calls[3]
  expect(String(rollbackUrl)).toContain('/api/templates/t1/rollback/3')
  expect(rollbackOpts.method).toBe('POST')
})

it('appends session_id to session-scoped list requests', async () => {
  fetchMock.mockResolvedValue(okJson({ runs: [], findings: [], evidence: [], assets: [] }))
  vi.stubGlobal('fetch', fetchMock)

  await listRuns('conv_1')
  expect(String(fetchMock.mock.calls[0][0])).toContain('/api/runs?session_id=conv_1')

  await listFindings('conv_1')
  expect(String(fetchMock.mock.calls[1][0])).toContain('/api/findings?session_id=conv_1')

  await listEvidence('conv_1')
  expect(String(fetchMock.mock.calls[2][0])).toContain('/api/evidence?session_id=conv_1')

  await listAssets({ session_id: 'conv_1' })
  expect(String(fetchMock.mock.calls[3][0])).toContain('/api/assets?session_id=conv_1')
})

it('startRun sends session_id in the body', async () => {
  fetchMock.mockResolvedValue(okJson({ id: 'r1' }))
  vi.stubGlobal('fetch', fetchMock)

  await startRun({ id: 't1' } as never, 'example.com', false, false, [], 'conv_1')
  const [, opts] = fetchMock.mock.calls[0]
  expect(JSON.parse(opts.body)).toMatchObject({ session_id: 'conv_1' })
})

it('stopRun posts to the run stop endpoint', async () => {
  fetchMock.mockResolvedValue(okJson({ stopped: 'r1' }))
  vi.stubGlobal('fetch', fetchMock)

  await stopRun('r1')
  const [url, opts] = fetchMock.mock.calls[0]
  expect(String(url)).toContain('/api/runs/r1/stop')
  expect(opts.method).toBe('POST')
})

it('exposes the M2/M3 import, version and evolution endpoints as functions', () => {
  // Rework ① guard: api.ts must only import type names that types.ts actually
  // exports — phantom type imports (EvolutionRunSummary/TemplateVersionInfo
  // were the real ones) survive vitest but fail `npm run build` (tsc -b).
  // Type-only breakage can't be asserted at runtime, so the build itself is
  // part of the per-PR self-check; this pins the module surface that the
  // wizard/evolution UI depends on.
  for (const name of [
    'inspectImport',
    'confirmImport',
    'generateOutputSchema',
    'listEvolutionRuns',
    'listTemplateVersions',
    'getTemplateVersion',
    'restoreTemplateVersion',
    'previewSuggestion',
    'applyWorkflowSuggestion',
  ] as const) {
    expect(typeof (api as Record<string, unknown>)[name]).toBe('function')
  }
})
