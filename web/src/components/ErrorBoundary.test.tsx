import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { ErrorBoundary } from './ErrorBoundary'

function Boom(): never {
  throw new Error('boom-explosion')
}

test('a render crash shows the fallback instead of blanking the app', () => {
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
  render(
    <ErrorBoundary>
      <Boom />
    </ErrorBoundary>,
  )
  expect(screen.getByText('页面出错了')).toBeTruthy()
  expect(screen.getByText(/boom-explosion/)).toBeTruthy()
  spy.mockRestore()
})

test('retry resets the boundary and renders recovered children', () => {
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
  const { rerender } = render(
    <ErrorBoundary>
      <Boom />
    </ErrorBoundary>,
  )
  rerender(
    <ErrorBoundary>
      <div>recovered-content</div>
    </ErrorBoundary>,
  )
  // error state persists until the user retries
  expect(screen.queryByText('recovered-content')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(screen.getByText('recovered-content')).toBeTruthy()
  spy.mockRestore()
})
