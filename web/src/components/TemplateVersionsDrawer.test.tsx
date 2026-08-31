import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import TemplateVersionsDrawer from './TemplateVersionsDrawer'
import * as api from '../api'
import type { TemplateVersionInfo } from '../api'

vi.mock('../api', () => ({
  getTemplate: vi.fn(),
  getTemplateVersion: vi.fn(),
  listTemplateVersions: vi.fn(),
  restoreTemplateVersion: vi.fn(),
}))

const mockedApi = vi.mocked(api)

const versions: TemplateVersionInfo[] = [
  { version: 1, lineage: { source: 'manual', ref_id: '' }, saved_at: '2026-08-29T10:00:00', current: false },
  { version: 2, lineage: { source: 'refine', ref_id: '' }, saved_at: '2026-08-30T10:00:00', current: false },
  { version: 3, lineage: { source: 'selfcheck', ref_id: 'run-1' }, saved_at: '2026-08-30T11:00:00', current: true },
]

beforeEach(() => {
  vi.clearAllMocks()
  mockedApi.listTemplateVersions.mockResolvedValue({ total: 3, offset: 0, limit: 20, versions })
  mockedApi.getTemplate.mockResolvedValue({
    id: 't1',
    name: 'n',
    start: 'a',
    stages: [{ id: 'a', name: 'a', depends_on: [] }],
    tools: [],
  })
})

test('lists versions with lineage labels and marks the current one', async () => {
  render(<TemplateVersionsDrawer templateId="t1" onClose={() => {}} />)

  expect(await screen.findByText('v1')).toBeTruthy()
  expect(screen.getByText('AI 优化')).toBeTruthy()
  expect(screen.getByText('运行建议')).toBeTruthy()
  expect(screen.getByText('当前')).toBeTruthy()
  // the current version offers no restore button
  const restoreButtons = screen.getAllByRole('button', { name: '以此版本另存新版本' })
  expect(restoreButtons).toHaveLength(2)
})

test('diff against current shows changed connections', async () => {
  mockedApi.getTemplateVersion.mockResolvedValue({
    version: 2,
    lineage: { source: 'refine', ref_id: '' },
    template: {
      id: 't1',
      name: 'n',
      start: 'a',
      stages: [
        { id: 'a', name: 'a', depends_on: [] },
        { id: 'b', name: 'b', depends_on: ['a'] },
      ],
      tools: [],
    },
  })
  render(<TemplateVersionsDrawer templateId="t1" onClose={() => {}} />)

  await userEvent.click((await screen.findAllByRole('button', { name: '与当前版本对比' }))[0])
  expect(await screen.findByText(/b/)).toBeTruthy()
})

test('restore copies a historical version on top of the chain', async () => {
  mockedApi.restoreTemplateVersion.mockResolvedValue({ new_version: 4 })
  const onRestored = vi.fn()
  render(<TemplateVersionsDrawer templateId="t1" onClose={() => {}} onRestored={onRestored} />)

  const buttons = await screen.findAllByRole('button', { name: '以此版本另存新版本' })
  await userEvent.click(buttons[0])

  expect(await screen.findByText(/已另存为新版本 v4/)).toBeTruthy()
  expect(mockedApi.restoreTemplateVersion).toHaveBeenCalledWith('t1', 1)
  expect(onRestored).toHaveBeenCalledWith(4)
})
