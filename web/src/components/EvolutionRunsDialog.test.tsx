import { render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import EvolutionRunsDialog from './EvolutionRunsDialog'
import * as api from '../api'

vi.mock('../api', () => ({
  listEvolutionRuns: vi.fn(),
}))

const mockedApi = vi.mocked(api)

beforeEach(() => {
  vi.clearAllMocks()
})

test('lists recent runs carrying suggestions and deep-links to the report', async () => {
  mockedApi.listEvolutionRuns.mockResolvedValue({
    runs: [
      { run_id: 'run-abc12345', created_at: '2026-08-30T10:00:00', target: 'example.com', summary: '建议增加验证阶段', suggestion_count: 2 },
    ],
  })
  render(<EvolutionRunsDialog templateId="t1" templateName="演示模板" onClose={() => {}} />)

  expect(await screen.findByText('来自运行的改进建议')).toBeTruthy()
  expect(screen.getByText('run-abc1')).toBeTruthy()
  expect(screen.getByText(/建议增加验证阶段/)).toBeTruthy()

  screen.getByRole('button', { name: '打开运行报告' }).click()
  expect(window.location.hash).toBe('#/run?template=t1&run=run-abc12345')
})

test('shows the empty state when no runs carry suggestions', async () => {
  mockedApi.listEvolutionRuns.mockResolvedValue({ runs: [] })
  render(<EvolutionRunsDialog templateId="t1" templateName="演示模板" onClose={() => {}} />)
  expect(await screen.findByText('近期运行没有产生改进建议。')).toBeTruthy()
})
