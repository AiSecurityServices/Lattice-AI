import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import ImportWizard from './ImportWizard'
import * as api from '../../api'
import type { ImportInspectResult, Tool } from '../../types'

vi.mock('../../api', () => ({
  inspectImport: vi.fn(),
  confirmImport: vi.fn(),
  generateOutputSchema: vi.fn(),
  saveImportedTool: vi.fn(),
  tryImportedTool: vi.fn(),
  executeImportedTool: vi.fn(),
}))

const mockedApi = vi.mocked(api)

const draft: Tool = {
  name: 'nmap_sv',
  description: 'Service scanner',
  runner: 'cli',
  command: ['nmap', '-sV', '-oX', '-', '{target}'],
  parameters: { type: 'object', properties: { target: { type: 'string' } }, required: ['target'] },
  output: { type: 'object', properties: { ports: { type: 'string' } } },
  approval: 'ask',
}

function completed(): ImportInspectResult {
  return { status: 'completed', draft, missing: { secrets: [], tools: [], approvals: [] }, warnings: [] }
}

beforeEach(() => {
  vi.clearAllMocks()
})

test('failed inspect shows the reason and the retry hint', async () => {
  mockedApi.inspectImport.mockResolvedValue({
    status: 'failed',
    reason: '无法解析导入内容',
    draft: null,
    missing: { secrets: [], tools: [], approvals: [] },
    warnings: [],
  })
  render(<ImportWizard onClose={() => {}} />)
  await userEvent.type(screen.getByRole('textbox'), 'garbage input!!!')
  await userEvent.click(screen.getByRole('button', { name: '解析预检' }))
  expect(await screen.findByText('解析失败')).toBeTruthy()
  expect(screen.getByText('无法解析导入内容')).toBeTruthy()
  expect(screen.getByText('请修改内容后重新解析')).toBeTruthy()
})

test('completed draft walks preview → trial → save and stores via the API', async () => {
  mockedApi.inspectImport.mockResolvedValue(completed())
  mockedApi.tryImportedTool.mockResolvedValue({ approval_id: 'a1', tool: 'nmap_sv', args: {} })
  mockedApi.executeImportedTool.mockResolvedValue({ tool: 'nmap_sv', result: { stdout: '22/tcp open' } })
  mockedApi.saveImportedTool.mockResolvedValue({ name: 'nmap_sv' })
  const onImported = vi.fn()

  render(<ImportWizard onClose={() => {}} onImported={onImported} />)
  await userEvent.type(screen.getByRole('textbox'), 'nmap -sV -oX - {target}')
  await userEvent.click(screen.getByRole('button', { name: '解析预检' }))

  expect(await screen.findByText('解析完成')).toBeTruthy()

  await userEvent.click(screen.getByRole('button', { name: '下一步' })) // inspect → preview
  expect(await screen.findByText(/nmap_sv/)).toBeTruthy()

  await userEvent.click(screen.getByRole('button', { name: '下一步' })) // preview → trial
  await userEvent.type(screen.getByLabelText('试运行目标'), 'example.com')
  await userEvent.click(screen.getByRole('button', { name: '试运行' }))
  expect(await screen.findByText(/22\/tcp open/)).toBeTruthy()

  await userEvent.click(screen.getByRole('button', { name: '下一步' })) // trial → save
  await userEvent.click(screen.getByRole('button', { name: '入库' }))

  expect(await screen.findByText('工具已入库')).toBeTruthy()
  expect(mockedApi.saveImportedTool).toHaveBeenCalledTimes(1)
  expect(onImported).toHaveBeenCalledTimes(1)
})

test('pending draft renders secret inputs and confirms with fills', async () => {
  mockedApi.inspectImport.mockResolvedValue({
    status: 'pending',
    draft_id: 'd1',
    draft: { ...draft, command: ['mytool', '--api-key', '[REDACTED]', '{target}'] },
    missing: { secrets: ['api_key'], tools: [], approvals: [] },
    warnings: [],
  })
  mockedApi.confirmImport.mockResolvedValue({ name: 'nmap_sv', tool: draft })

  render(<ImportWizard onClose={() => {}} />)
  await userEvent.type(screen.getByRole('textbox'), 'mytool --api-key sk-live-xxx {target}')
  await userEvent.click(screen.getByRole('button', { name: '解析预检' }))

  expect(await screen.findByText('需要补充信息')).toBeTruthy()
  await userEvent.type(screen.getByLabelText(/需要补齐的凭证/), 'sk-real-999')
  await userEvent.click(screen.getByRole('button', { name: '入库' }))

  expect(await screen.findByText('工具已入库')).toBeTruthy()
  expect(mockedApi.confirmImport).toHaveBeenCalledWith(
    expect.objectContaining({ draft_id: 'd1', fills: { secrets: { api_key: 'sk-real-999' } } }),
  )
})
