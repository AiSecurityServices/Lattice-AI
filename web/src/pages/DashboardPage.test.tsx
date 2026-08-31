import { render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import DashboardPage from './DashboardPage'
import * as api from '../api'
import type { DashboardData } from '../types'

vi.mock('../api', () => ({
  getDashboard: vi.fn(),
}))

const mockedApi = vi.mocked(api)

const data: DashboardData = {
  session_id: 'conv1',
  days: ['2026-08-24', '2026-08-25', '2026-08-26', '2026-08-27', '2026-08-28', '2026-08-29', '2026-08-30'],
  kpis: {
    assets: { total: 12, spark: [0, 1, 2, 3, 2, 2, 2] },
    subdomains: { total: 8, spark: [0, 1, 1, 2, 2, 1, 1] },
    findings: {
      total: 5,
      severity: { critical: 1, high: 2, medium: 1, low: 1, info: 0 },
      spark: [0, 0, 1, 1, 2, 1, 0],
    },
    runs: { total: 4, spark: [0, 1, 0, 1, 1, 0, 1] },
  },
  recent_runs: [
    { id: 'run1', template_id: 'web-app-standard', target: 'example.com', kind: 'run', created_at: '2026-08-30T10:00:00' },
  ],
  recent_findings: [
    {
      id: 'f1',
      title: 'SQL 注入',
      severity: 'critical',
      status: 'pending',
      target: 'example.com',
      run_id: 'run1',
      created_at: '2026-08-30T10:00:00',
    },
  ],
}

beforeEach(() => {
  mockedApi.getDashboard.mockResolvedValue(data)
})

test('renders four KPI cards with totals and critical+high sub count', async () => {
  render(<DashboardPage refreshKey={0} sessionId="conv1" onNavigate={() => {}} />)
  expect(await screen.findByText('12')).toBeTruthy()
  expect(screen.getByText('资产')).toBeTruthy()
  expect(screen.getByText('子域名')).toBeTruthy()
  expect(screen.getByText('漏洞发现')).toBeTruthy()
  expect(screen.getByText('运行次数')).toBeTruthy()
  expect(screen.getByText('严重+高危 3')).toBeTruthy()
  expect(document.querySelectorAll('.sparkline').length).toBe(4)
})

test('renders dual feed with severity dot badges', async () => {
  render(<DashboardPage refreshKey={0} sessionId="conv1" onNavigate={() => {}} />)
  expect(await screen.findByText('最近运行')).toBeTruthy()
  expect(await screen.findByText('最近发现')).toBeTruthy()
  expect(screen.getAllByText('example.com').length).toBeGreaterThan(0)
  expect(screen.getByText('SQL 注入')).toBeTruthy()
  expect(document.querySelector('.sev-dot.sev-critical')).toBeTruthy()
})

test('shows empty state when no runs or findings', async () => {
  mockedApi.getDashboard.mockResolvedValue({
    ...data,
    recent_runs: [],
    recent_findings: [],
  })
  render(<DashboardPage refreshKey={0} sessionId="conv1" onNavigate={() => {}} />)
  expect(await screen.findByText('还没有运行记录，去任务页发起一次扫描吧。')).toBeTruthy()
  expect(screen.getByText('还没有发现，运行工作流后这里会显示最新漏洞。')).toBeTruthy()
})

test('navigating from feeds calls onNavigate with the target module', async () => {
  const onNavigate = vi.fn()
  render(<DashboardPage refreshKey={0} sessionId="conv1" onNavigate={onNavigate} />)
  const buttons = await screen.findAllByRole('button', { name: /查看全部/ })
  expect(buttons.length).toBe(2)
})

test('aggregates at project level: no session filter even when a session is passed', async () => {
  // 回归（P1）：把对话 ID 传给 session_id 会把项目数据过滤成全 0；
  // 页面必须固定传空 session_id 拿项目级全量。
  mockedApi.getDashboard.mockResolvedValue({
    ...data,
    kpis: {
      ...data.kpis,
      assets: { total: 36, spark: [1, 2, 3, 4, 5, 6, 7] },
      runs: { total: 6, spark: [0, 1, 1, 1, 1, 1, 1] },
    },
  })
  render(<DashboardPage refreshKey={0} sessionId="conv_35854c35" onNavigate={() => {}} />)
  expect(mockedApi.getDashboard).toHaveBeenCalledWith('')
  expect(await screen.findByText('36')).toBeTruthy()
  expect(screen.getByText('6')).toBeTruthy()
})
