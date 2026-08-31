import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastHost } from './Toast'
import { toast } from '../../lib/toast'

describe('ToastHost', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders a fired toast', () => {
    render(<ToastHost />)
    act(() => toast('保存失败', 'error'))
    expect(screen.getByText('保存失败')).toBeTruthy()
  })

  it('dismisses toasts after a timeout', () => {
    render(<ToastHost />)
    act(() => toast('hello', 'info'))
    expect(screen.getByText('hello')).toBeTruthy()
    act(() => {
      vi.advanceTimersByTime(4500)
    })
    expect(screen.queryByText('hello')).toBeNull()
  })

  it('stacks multiple toasts', () => {
    render(<ToastHost />)
    act(() => {
      toast('one', 'info')
      toast('two', 'error')
    })
    expect(screen.getByText('one')).toBeTruthy()
    expect(screen.getByText('two')).toBeTruthy()
  })

  it('does not render anything without toasts', () => {
    render(<ToastHost />)
    expect(document.querySelector('.toast-host')).toBeNull()
    fireEvent(window, new Event('lattice:noop'))
    expect(document.querySelector('.toast-host')).toBeNull()
  })
})
