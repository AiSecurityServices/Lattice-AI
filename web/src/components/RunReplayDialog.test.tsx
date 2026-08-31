import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { RunReplayDialog } from './RunReplayDialog'
import * as api from '../api'

vi.mock('../api', () => ({ replayRun: vi.fn().mockResolvedValue({ run_id: 'r1', events: [], next_after: 0, has_more: false }) }))

test('renders replay dialog', async () => {
  render(<RunReplayDialog runId="r1" onClose={() => {}} />)
  expect(await screen.findByText('运行回放')).toBeTruthy()
  expect(api.replayRun).toHaveBeenCalledWith('r1', 0)
})
