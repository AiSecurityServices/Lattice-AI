import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ToolchainSection } from './ToolchainSection'

vi.mock('../../api', () => ({
  listToolchain: vi.fn().mockResolvedValue({ tools: [{ name: 'nuclei', available: false, status: 'missing' }] }),
  getToolchainInstallStatus: vi.fn(),
  installToolchain: vi.fn(),
}))

describe('ToolchainSection', () => {
  it('lists tools', async () => {
    render(<ToolchainSection />)
    expect(await screen.findByText('nuclei')).toBeInTheDocument()
    expect(screen.getByText('缺失')).toBeInTheDocument()
  })
})
