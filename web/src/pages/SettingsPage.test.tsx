import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import SettingsPage from './SettingsPage'

vi.mock('../api', () => ({
  getSettings: vi.fn().mockResolvedValue({ provider: 'custom', base_url: 'https://example.com/v1', model: 'm1', api_key: '', reasoning_effort: '', has_api_key: false }),
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
  listToolchain: vi.fn().mockResolvedValue({ tools: [] }),
  installToolchain: vi.fn(),
  getToolchainInstallStatus: vi.fn(),
}))

test('renders settings shell', async () => {
  render(<SettingsPage />)
  expect(await screen.findByText('Base URL')).toBeInTheDocument()
})
