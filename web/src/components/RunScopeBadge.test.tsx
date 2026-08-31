import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RunScopeBadge } from './RunScopeBadge'

vi.mock('../api', () => ({
  getScope: vi.fn().mockResolvedValue({
    allow_domains: ['example.com'],
    allow_ips: [],
    allow_cidrs: ['10.0.0.0/8'],
    allow_ports: [80, 443],
    allow_url_prefixes: [],
  }),
}))

describe('RunScopeBadge', () => {
  it('renders authorization boundary and subdomain note', async () => {
    render(<RunScopeBadge />)
    const span = await screen.findByText((_, node) => node?.tagName === 'SPAN' && !!node?.textContent?.includes('授权范围：'))
    expect(span.textContent).toContain('域名 example.com（含子域）')
    expect(span.textContent).toContain('10.0.0.0/8')
    expect(span.textContent).toContain('无需预填')
  })

  it('prompts when scope is unconfigured', async () => {
    vi.mocked((await import('../api')).getScope).mockResolvedValue({
      allow_domains: [],
      allow_ips: [],
      allow_cidrs: [],
      allow_ports: [],
      allow_url_prefixes: [],
    })
    render(<RunScopeBadge />)
    expect(await screen.findByText(/尚未配置授权范围/)).toBeInTheDocument()
  })
})
