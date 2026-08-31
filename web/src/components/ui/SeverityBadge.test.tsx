import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { SeverityBadge, severityKey } from './SeverityBadge'

it('renders the label with the matching sev-* class', () => {
  render(<SeverityBadge severity="critical" />)
  const badge = screen.getByText('严重')
  expect(badge.className).toContain('sev-badge')
  expect(badge.className).toContain('sev-critical')
})

it('maps unknown severities to info', () => {
  expect(severityKey('unknown')).toBe('info')
  expect(severityKey('high')).toBe('high')
  const { container } = render(<SeverityBadge severity="nonsense" />)
  expect(container.querySelector('.sev-info')).toBeTruthy()
})

it('supports custom content such as risk labels', () => {
  render(<SeverityBadge severity="high">风险：high</SeverityBadge>)
  expect(screen.getByText('风险：high').className).toContain('sev-high')
})
