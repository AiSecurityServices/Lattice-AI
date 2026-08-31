import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GenerateTemplateDialog } from './GenerateTemplateDialog'

const fetchMock = vi.fn()

function streamResponse(events: unknown[]) {
  const body = events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('')
  return new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body))
      controller.close()
    },
  })
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('GenerateTemplateDialog', () => {
  it('submits a description and shows the report on complete', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, text: async () => '', json: async () => ({ job_id: 'job-1' }) })
      .mockResolvedValueOnce({
        ok: true,
        body: streamResponse([
          { type: 'complete', template: { id: 't1', name: 'Demo', start: 'a', stages: [{ id: 'a', name: 'A' }], tools: [], skills: [] }, report: { confidence: 'low', issues: [], imports: { tools: [], skills: [] } } },
        ]),
      })

    render(<GenerateTemplateDialog open onCancel={vi.fn()} onApplied={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: '一句话描述' }))
    await userEvent.type(screen.getByPlaceholderText('或用一句话描述要生成的模板'), '一个扫描器')
    await userEvent.click(screen.getByRole('button', { name: '生成' }))

    await waitFor(() => expect(screen.getByText(/置信度/)).toBeInTheDocument())
    expect(screen.getByText('Demo')).toBeInTheDocument()
  })
})
