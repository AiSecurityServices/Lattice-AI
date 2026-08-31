import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { NodeRunDrawer, type DrawerToolEvent } from './NodeRunDrawer'
import type { StageExecutionRow } from '../../api'
import '../../index.css'

const row: StageExecutionRow = {
  run_id: 'r1',
  stage_id: 'a',
  status: 'completed',
  started_at: '2026-08-30T00:00:00',
  finished_at: '2026-08-30T00:00:02',
  elapsed_ms: 1834,
  tool_calls: 2,
  llm_calls: 1,
  tokens_in: 320,
  tokens_out: 96,
  error: '',
}

const events: DrawerToolEvent[] = [
  { kind: 'call', tool: 'httpx', args: { target: 'example.com' } },
  { kind: 'result', tool: 'httpx', key: 'httpx', result: { url: 'http://example.com', status: 200 } },
]

test('renders three tabs and defaults to the result tab', () => {
  render(<NodeRunDrawer stageId="a" stageName="存活发现" stageStatus="completed" factKeys={['httpx']} facts={{ httpx: { url: 'http://example.com' } }} toolEvents={events} execution={row} onClose={() => {}} />)
  expect(screen.getByText('存活发现')).toBeTruthy()
  expect(screen.getByRole('tab', { name: /结果/ })).toBeTruthy()
  expect(screen.getByText('httpx')).toBeTruthy() // fact key heading
  expect(screen.getAllByText(/example.com/).length).toBeGreaterThan(0)
})

test('process tab lists tool events with token estimate badges', () => {
  render(<NodeRunDrawer stageId="a" toolEvents={events} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('tab', { name: /过程/ }))
  expect(screen.getAllByText('tool_call').length).toBeGreaterThan(0)
  expect(screen.getAllByText('tool_result').length).toBeGreaterThan(0)
  // estimate from the JSON length (placeholder until E1 tokens land per tool)
  expect(screen.getByText(/≈\d+ tokens/)).toBeTruthy()
})

test('trace tab shows the execution row telemetry', () => {
  render(<NodeRunDrawer stageId="a" execution={row} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('tab', { name: /追踪/ }))
  expect(screen.getByText('1834 ms')).toBeTruthy()
  expect(screen.getByText('已完成')).toBeTruthy()
  expect(screen.getByText('320 / 96')).toBeTruthy()
  expect(screen.getByText('2')).toBeTruthy() // tool calls
})

test('running stage without data renders skeletons in every tab', () => {
  render(<NodeRunDrawer stageId="b" stageStatus="running" onClose={() => {}} />)
  expect(document.querySelectorAll('.node-drawer-skeleton .skeleton').length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole('tab', { name: /过程/ }))
  expect(document.querySelectorAll('.node-drawer-skeleton .skeleton').length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole('tab', { name: /追踪/ }))
  expect(document.querySelectorAll('.node-drawer-skeleton .skeleton').length).toBeGreaterThan(0)
})

test('close button and closed state', () => {
  const onClose = () => {}
  const { rerender } = render(<NodeRunDrawer stageId="a" onClose={onClose} />)
  expect(screen.getByTestId('node-drawer')).toBeTruthy()
  rerender(<NodeRunDrawer stageId={null} onClose={onClose} />)
  expect(screen.queryByTestId('node-drawer')).toBeNull()
})
