import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { GroundingBadge } from './GroundingBadge'

test('renders the three verdict states with labels', () => {
  render(
    <>
      <GroundingBadge status="verified" />
      <GroundingBadge status="unverified" />
      <GroundingBadge status="missing_evidence" />
    </>,
  )
  expect(screen.getByText('已核验')).toBeTruthy()
  expect(screen.getByText('未核验')).toBeTruthy()
  expect(screen.getByText('缺证据')).toBeTruthy()
})

test('renders nothing without a verdict (policy=off / legacy data)', () => {
  const { container } = render(
    <>
      <GroundingBadge status={undefined} />
      <GroundingBadge status={null} />
      <GroundingBadge />
    </>,
  )
  expect(container.textContent).toBe('')
})

test('unknown status strings render nothing instead of a broken badge', () => {
  const { container } = render(<GroundingBadge status="bogus" />)
  expect(container.textContent).toBe('')
})
