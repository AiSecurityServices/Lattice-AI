import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { RunReport, groundingStatsOf } from './RunReport'
import * as api from '../api'
import type { RunResult } from '../types'
import '../index.css'

vi.mock('../api', () => ({
  applyWorkflowSuggestion: vi.fn(),
  saveTemplate: vi.fn(),
  listFindings: vi.fn(),
}))

const mockedApi = vi.mocked(api)

const run: RunResult = {
  id: 'r1',
  report: 'found 80 open port',
  facts: { target: '10.0.0.1', risk: 'high' },
  events: [{ seq: 1, type: 'stage', data: { name: 'port-scan' } }],
}

describe('RunReport', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.listFindings.mockResolvedValue({ findings: [] })
  })

  it('renders report and timeline', () => {
    render(<RunReport run={run} />)
    expect(screen.getByText('found 80 open port')).toBeInTheDocument()
    expect(screen.getByText(/port-scan/)).toBeInTheDocument()
  })

  it('shows self-check tab when evolution present', async () => {
    const withEvolution: RunResult = {
      id: 'r2',
      facts: { target: '10.0.0.1' },
      events: [],
      report: '# Report',
      evolution: {
        summary: 'overall-ok',
        steps: [],
        suggestions: [{ type: 'add_tool', where: 's1', detail: 'bind dnsx' }],
        unresolved: [],
        confidence: 'low',
      },
    }
    render(<RunReport run={withEvolution} />)
    expect(screen.getByRole('button', { name: /自检/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /自检/ }))
    expect(screen.getByText(/overall-ok/)).toBeInTheDocument()
  })

  it('keeps report and self-check containers bounded and scrollable', async () => {
    const { container } = render(<RunReport run={run} />)
    const summary = container.querySelector('.report-summary')!
    expect(getComputedStyle(summary).overflowY).toBe('auto')
    expect(getComputedStyle(summary).maxHeight).toBe('100%')

    const withEvolution: RunResult = {
      id: 'r3',
      facts: {},
      events: [],
      report: '# Report',
      evolution: { summary: 'ok', steps: [], suggestions: [], unresolved: [], confidence: 'low' },
    }
    const { container: evolutionContainer } = render(<RunReport run={withEvolution} />)
    await userEvent.click(screen.getByRole('button', { name: /自检/ }))
    const selfCheck = evolutionContainer.querySelector('.self-check-report')!
    expect(getComputedStyle(selfCheck).overflowY).toBe('auto')
    expect(getComputedStyle(selfCheck).maxHeight).toBe('100%')
  })
})

describe('RunReport grounding stats', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('groundingStatsOf buckets findings by verdict', () => {
    const stats = groundingStatsOf([
      { run_id: 'r1', grounding: { status: 'verified' } },
      { run_id: 'r1', grounding: { status: 'verified' } },
      { run_id: 'r1', grounding: { status: 'unverified' } },
      { run_id: 'r1', grounding: { status: 'missing_evidence' } },
      { run_id: 'r1' }, // policy=off: no verdict, not counted
    ])
    expect(stats).toEqual({ verified: 2, unverified: 1, missing_evidence: 1 })
  })

  it('shows the verified/unverified/missing triple in the report header', async () => {
    mockedApi.listFindings.mockResolvedValue({
      findings: [
        { id: 'f1', run_id: 'r1', severity: 'high', status: 'confirmed', title: 'a', grounding: { status: 'verified' } },
        { id: 'f2', run_id: 'r1', severity: 'high', status: 'confirmed', title: 'b', grounding: { status: 'unverified' } },
        { id: 'f3', run_id: 'r1', severity: 'high', status: 'confirmed', title: 'c', grounding: { status: 'missing_evidence' } },
        { id: 'f4', run_id: 'other-run', severity: 'high', status: 'confirmed', title: 'd', grounding: { status: 'verified' } },
      ],
    })
    render(<RunReport run={run} />)
    expect(await screen.findByText(/证据核验：已核验 1 \/ 未核验 1 \/ 缺证据 1/)).toBeTruthy()
  })

  it('hides the stats line when the run has no grounded findings', async () => {
    mockedApi.listFindings.mockResolvedValue({ findings: [{ id: 'f9', run_id: 'r1', severity: 'low', status: 'pending', title: 'legacy' }] })
    render(<RunReport run={run} />)
    await api.listFindings('').then(() => {}) // flush the effect fetch
    expect(screen.queryByText(/证据核验/)).toBeNull()
  })
})
