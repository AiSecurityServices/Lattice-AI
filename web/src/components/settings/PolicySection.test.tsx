import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PolicySection } from './PolicySection'

vi.mock('../../api', () => ({
  getSecuritySettings: vi.fn().mockResolvedValue({ level: 'standard', whitelist: [] }),
  putSecuritySettings: vi.fn().mockResolvedValue({}),
}))

describe('PolicySection', () => {
  it('renders danger levels', async () => {
    render(<PolicySection />)
    expect(await screen.findByText('严格')).toBeInTheDocument()
  })
})
