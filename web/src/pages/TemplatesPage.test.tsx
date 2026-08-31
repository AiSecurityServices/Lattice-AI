import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import TemplatesPage from './TemplatesPage'
import * as api from '../api'

vi.mock('../api', () => ({
  listTemplates: vi.fn(),
  listMarketplace: vi.fn(),
  installMarketplace: vi.fn(),
  installStatus: vi.fn(),
  cloneTemplate: vi.fn(),
  deleteTemplate: vi.fn(),
  getTemplate: vi.fn(),
  renameTemplate: vi.fn(),
  saveTemplate: vi.fn(),
  listToolchainRegistry: vi.fn(),
}))

const mockedApi = vi.mocked(api)

beforeEach(() => {
  mockedApi.listTemplates.mockResolvedValue({ templates: [] })
  mockedApi.listMarketplace.mockResolvedValue({
    templates: [
      {
        id: 'builtin-full-pentest-lite',
        name: '全流程渗透测试（轻量版）',
        description: 'd',
        needs_tools: ['nuclei'],
        tools_installed: { nuclei: false },
      },
    ],
  })
  mockedApi.listToolchainRegistry.mockResolvedValue({
    registry: [
      { name: 'nuclei', installed: true },
      { name: 'subfinder', installed: false },
    ] as never[],
  })
  mockedApi.installMarketplace.mockResolvedValue({ id: 'builtin-full-pentest-lite', name: 'x', job_id: 'job1', status: 'installing' })
  mockedApi.installStatus.mockResolvedValue({
    job_id: 'job1',
    status: 'done',
    error: null,
    tools_installed: { nuclei: false },
    results: [{ name: 'nuclei', status: 'failed', detail: 'no go' }],
  })
})

test('renders built-in module panel with needs-tools badge', async () => {
  render(<TemplatesPage onOpen={() => {}} refreshKey={0} />)
  expect(await screen.findByText('内置模块')).toBeTruthy()
  expect(await screen.findByText(/需安装工具/)).toBeTruthy()
})

test('install button calls installMarketplace and shows failure', async () => {
  render(<TemplatesPage onOpen={() => {}} refreshKey={0} />)
  const btn = await screen.findByRole('button', { name: /安装/ })
  fireEvent.click(btn)
  await waitFor(() => expect(mockedApi.installMarketplace).toHaveBeenCalledWith('builtin-full-pentest-lite'))
  await waitFor(() => expect(screen.getByText(/安装失败/)).toBeTruthy())
})

const matrixTemplates = [
  { id: 'matrix-web-standard', name: 'Web 标准评估' },
  { id: 'matrix-recon-domain-lite', name: '域名侦察-快筛' },
]

const matrixMetas: Record<string, Record<string, unknown>> = {
  'matrix-web-standard': {
    id: 'matrix-web-standard',
    summary: '标准 Web 评估流水线',
    depth: 'standard',
    target_type: 'web',
    tags: ['web', 'standard'],
    stages: [
      { id: 'normalize' },
      { id: 'injection', tools: [{ tool: 'nuclei' }] },
    ],
  },
  'matrix-recon-domain-lite': {
    id: 'matrix-recon-domain-lite',
    summary: '三步被动侦察',
    depth: 'lite',
    target_type: 'domain',
    tags: ['recon'],
    stages: [{ id: 'subdomain', tools: [{ tool: 'subfinder' }, { tool: 'whatweb' }] }],
  },
}

test('matrix cards show depth/target badges, stage count and tool install state', async () => {
  mockedApi.listTemplates.mockResolvedValue({ templates: matrixTemplates })
  mockedApi.getTemplate.mockImplementation(((id: string) =>
    Promise.resolve(matrixMetas[id])) as unknown as typeof api.getTemplate)
  render(<TemplatesPage onOpen={() => {}} refreshKey={0} />)
  expect(await screen.findByText('标准')).toBeTruthy() // depth badge zh
  expect(screen.getByText('Web 标准评估')).toBeTruthy()
  expect(screen.getByText('2 阶段')).toBeTruthy()
  // nuclei installed, subfinder missing -> lite card shows missing tools
  expect(screen.getByText(/缺工具: subfinder/)).toBeTruthy()
  const webCard = screen.getByText('Web 标准评估').closest('.template-card')!
  expect(webCard.querySelector('.tpl-tools-missing')).toBeNull()
})

test('target x depth chips filter the matrix cards', async () => {
  mockedApi.listTemplates.mockResolvedValue({ templates: matrixTemplates })
  mockedApi.getTemplate.mockImplementation(((id: string) =>
    Promise.resolve(matrixMetas[id])) as unknown as typeof api.getTemplate)
  render(<TemplatesPage onOpen={() => {}} refreshKey={0} />)
  await screen.findByText('Web 标准评估')
  expect(screen.getByText('域名侦察-快筛')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '域名' }))
  expect(screen.queryByText('Web 标准评估')).toBeNull()
  expect(screen.getByText('域名侦察-快筛')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '快筛' }))
  expect(screen.getByText('域名侦察-快筛')).toBeTruthy()
  fireEvent.click(screen.getAllByRole('button', { name: '全部' })[0])
  fireEvent.click(screen.getAllByRole('button', { name: '全部' })[1])
  expect(screen.getByText('Web 标准评估')).toBeTruthy()
})
