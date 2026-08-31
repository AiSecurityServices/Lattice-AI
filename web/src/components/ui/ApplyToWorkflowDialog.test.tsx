import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ApplyToWorkflowDialog } from './ApplyToWorkflowDialog'
import type { Template } from '../../types'

const template: Template = {
  id: 't1',
  name: 'demo',
  start: 'a',
  stages: [
    { id: 'a', name: 'A', tools: [] },
    { id: 'b', name: 'B', tools: [] },
  ],
  tools: [],
}

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockResolvedValue({ ok: true, text: async () => '', json: async () => ({ id: 't1', name: 'demo' }) })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ApplyToWorkflowDialog', () => {
  it('writes the tool binding into every stage and calls onApplied', async () => {
    const onApplied = vi.fn()
    render(<ApplyToWorkflowDialog open kind="tool" items={['dnsx']} template={template} onCancel={vi.fn()} onApplied={onApplied} />)
    await userEvent.click(screen.getByRole('button', { name: '应用' }))

    await waitFor(() => expect(onApplied).toHaveBeenCalled())
    const putCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/api/templates/t1'))
    expect(putCall).toBeTruthy()
    const body = JSON.parse((putCall![1] as RequestInit).body as string)
    expect(body.stages[0].tools).toEqual([{ tool: 'dnsx', key: expect.any(String), note: '' }])
    expect(body.stages[1].tools).toEqual([{ tool: 'dnsx', key: expect.any(String), note: '' }])
  })

  it('applies to a single stage when a stage is scoped', async () => {
    const onApplied = vi.fn()
    render(<ApplyToWorkflowDialog open kind="skill" items={['report-format']} template={template} onCancel={vi.fn()} onApplied={onApplied} />)
    await userEvent.click(screen.getByRole('button', { name: '某阶段' }))
    await userEvent.click(screen.getByRole('button', { name: '应用' }))

    await waitFor(() => expect(onApplied).toHaveBeenCalled())
    const putCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/api/templates/t1'))
    const body = JSON.parse((putCall![1] as RequestInit).body as string)
    expect(body.stages[0].skills).toEqual([{ skill: 'report-format' }])
    expect(body.stages[1].skills ?? []).toEqual([])
  })
})
