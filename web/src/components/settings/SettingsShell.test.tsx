import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SettingsShell } from './SettingsShell'

vi.mock('../../api', () => ({
  getSettings: vi.fn().mockResolvedValue({ provider: 'custom', base_url: 'https://x/v1', model: 'm', api_key: '', reasoning_effort: '', has_api_key: false }),
  listProviders: vi.fn().mockResolvedValue({ providers: {} }),
  listModels: vi.fn().mockRejectedValue(new Error('not configured')),
  getScope: vi.fn().mockResolvedValue({}),
  getSecuritySettings: vi.fn().mockResolvedValue({}),
  putSettings: vi.fn(),
  putScope: vi.fn(),
  putSecuritySettings: vi.fn(),
  testProvider: vi.fn(),
  getPreferences: vi.fn().mockResolvedValue({ theme: 'system', language: 'zh' }),
  putPreferences: vi.fn(),
  listToolchain: vi.fn().mockResolvedValue({ tools: [{ name: 'nuclei', available: false, status: 'missing' }] }),
  installToolchain: vi.fn(),
  getToolchainInstallStatus: vi.fn(),
}))

describe('SettingsShell', () => {
  it('shows the nav and LLM panel by default', async () => {
    render(<SettingsShell />)
    expect(screen.getByText('模型与推理')).toBeInTheDocument()
    expect(await screen.findByText('LLM 提供商')).toBeInTheDocument()
  })
})
