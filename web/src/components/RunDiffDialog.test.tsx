import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { RunDiffDialog } from './RunDiffDialog'
import * as api from '../api'

vi.mock('../api', () => ({ diffRuns: vi.fn().mockResolvedValue({ base_run_id: 'b', head_run_id: 'h', findings: { added: [], removed: [], changed: [] }, assets: { added: [], removed: [], changed: [] }, evidence: { added: [], removed: [], changed: [] } }) }))

test('renders diff dialog', () => {
  render(<RunDiffDialog runs={[]} headRunId="h" onClose={() => {}} />)
  expect(screen.getByText('运行对比')).toBeTruthy()
})

test('runs diff for selected base run', async () => {
  const user = userEvent.setup()
  render(
    <RunDiffDialog
      runs={[
        { id: 'b1', template_id: 't', target: 'example.com' },
        { id: 'h', template_id: 't', target: 'example.org' },
      ]}
      headRunId="h"
      onClose={() => {}}
    />,
  )
  await user.selectOptions(screen.getByRole('combobox'), 'b1')
  await user.click(screen.getByRole('button', { name: '对比' }))
  expect(api.diffRuns).toHaveBeenCalledWith('b1', 'h')
  expect(await screen.findByText(/base_run_id/)).toBeTruthy()
})
