import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import EvolutionPanel from './EvolutionPanel'
import * as api from '../api'
import type { EvolutionReport, Template } from '../types'

vi.mock('../api', () => ({
  previewSuggestion: vi.fn(),
  applyWorkflowSuggestion: vi.fn(),
}))

const mockedApi = vi.mocked(api)

const template: Template = {
  id: 't1',
  name: '模板',
  start: 'a',
  stages: [{ id: 'a', name: 'a', depends_on: [] }],
  tools: [],
  version: 3,
}

const evolution: EvolutionReport = {
  summary: 'run summary',
  steps: [],
  suggestions: [
    { type: 'add_stage', stage_name: 'verify-x', after_stage_id: 'a', detail: '建议增加验证阶段' },
    { type: 'add_tool', stage_id: 'a', tool_name: 'nuclei', detail: '补充漏洞扫描' },
  ],
  unresolved: [],
  confidence: 'medium',
}

beforeEach(() => {
  vi.clearAllMocks()
})

test('renders each suggestion with a diff preview computed from the server', async () => {
  mockedApi.previewSuggestion.mockResolvedValue({
    template: {
      ...template,
      stages: [
        { id: 'a', name: 'a', depends_on: [] },
        { id: 'verify-x', name: 'verify-x', depends_on: ['a'] },
      ],
    },
  })
  render(<EvolutionPanel template={template} evolution={evolution} />)

  expect(await screen.findByText('改进建议')).toBeTruthy()
  expect(screen.getByText('add_stage')).toBeTruthy()
  expect(screen.getByText('add_tool')).toBeTruthy()
  // add_stage with after_stage_id=a creates a connection change a → [verify-x]... on the AFTER side
  expect((await screen.findAllByText(/verify-x/)).length).toBeGreaterThan(0)
  expect(mockedApi.previewSuggestion).toHaveBeenCalledTimes(2)
})

test('apply calls the suggestion endpoint and reports the new version', async () => {
  mockedApi.previewSuggestion.mockResolvedValue({ template })
  mockedApi.applyWorkflowSuggestion.mockResolvedValue({ template_id: 't1', new_version: 4, stages: ['a'] })
  const onApplied = vi.fn()
  render(<EvolutionPanel template={template} evolution={evolution} onApplied={onApplied} />)

  const buttons = await screen.findAllByRole('button', { name: '应用' })
  await userEvent.click(buttons[0])

  expect(await screen.findByText(/已应用并自动建版本快照 v4/)).toBeTruthy()
  expect(mockedApi.applyWorkflowSuggestion).toHaveBeenCalledWith('t1', evolution.suggestions![0])
  expect(onApplied).toHaveBeenCalledWith(4)
})
