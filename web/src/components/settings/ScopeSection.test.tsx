import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ScopeSection } from './ScopeSection'

vi.mock('../../api', () => ({
  getScope: vi.fn().mockResolvedValue({ allow_domains: [], allow_ips: [], allow_cidrs: [], allow_ports: [], allow_url_prefixes: [] }),
  putScope: vi.fn().mockResolvedValue({}),
}))

describe('ScopeSection', () => {
  it('renders domain chip input', async () => {
    render(<ScopeSection />)
    expect(await screen.findByLabelText('允许域名')).toBeInTheDocument()
  })
})
