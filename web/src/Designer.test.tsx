import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Designer from './Designer'
import type { Template } from './types'

vi.mock('./api', () => ({
  listTools: vi.fn().mockResolvedValue({ tools: [] }),
  listSkills: vi.fn().mockResolvedValue({ skills: [] }),
  understandWorkflow: vi.fn(),
}))

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const dagTemplate: Template = {
  id: 'dag-1',
  name: 'DAG',
  start: 'a',
  stages: [
    { id: 'a', name: 'A', depends_on: [] },
    { id: 'b', name: 'B', depends_on: ['a'] },
    { id: 'c', name: 'C', depends_on: ['b'], condition: { op: 'truthy', key: 'go' } },
  ],
  tools: [],
}

test('renders DAG template without transitions without crashing', () => {
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  render(<Designer template={dagTemplate} onTemplateChange={() => {}} onSave={() => {}} />)
  expect(screen.getByText('工作流编辑器')).toBeTruthy()
  expect(screen.getAllByText('A').length).toBeGreaterThan(0)
  expect(screen.getAllByText('B').length).toBeGreaterThan(0)
  expect(screen.getAllByText('C').length).toBeGreaterThan(0)
  vi.unstubAllGlobals()
})

test('edits stage condition and gate', () => {
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  const template = {
    id: 't',
    name: 'T',
    start: 'a',
    stages: [{ id: 'a', name: 'A', condition: null, gates: [], depends_on: [] }],
    tools: [],
  } as Template
  render(<Designer template={template} onTemplateChange={() => {}} onSave={() => {}} />)
  fireEvent.click(screen.getAllByText('A')[0])
  expect(screen.getAllByText(/入口条件（condition）/).length).toBeGreaterThan(0)
  expect(screen.getByText(/质量 gate/)).toBeTruthy()
  vi.unstubAllGlobals()
})
