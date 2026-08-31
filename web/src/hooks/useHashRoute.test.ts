import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { readHashParams, useHashRoute } from './useHashRoute'

describe('useHashRoute', () => {
  beforeEach(() => {
    window.location.hash = ''
  })
  it('defaults to run when no hash', () => {
    const { result } = renderHook(() => useHashRoute('run'))
    expect(result.current[0]).toBe('run')
  })
  it('reads a valid module hash', () => {
    window.location.hash = '#/findings'
    const { result } = renderHook(() => useHashRoute('run'))
    expect(result.current[0]).toBe('findings')
  })
  it('falls back on unknown hash', () => {
    window.location.hash = '#/bogus'
    const { result } = renderHook(() => useHashRoute('run'))
    expect(result.current[0]).toBe('run')
  })
  it('navigate writes the hash', () => {
    const { result } = renderHook(() => useHashRoute('run'))
    act(() => result.current[1]('trash'))
    expect(window.location.hash).toBe('#/trash')
    expect(result.current[0]).toBe('trash')
  })
  it('follows external hash changes (back/forward)', () => {
    const { result } = renderHook(() => useHashRoute('run'))
    act(() => result.current[1]('logs'))
    // jsdom does not fully emulate hashchange for history.back(); simulate the
    // browser behaviour: hash rewritten by navigation, event dispatched.
    window.location.hash = '#/tools'
    act(() => {
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(result.current[0]).toBe('tools')
    window.location.hash = '#/logs'
    act(() => {
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(result.current[0]).toBe('logs')
  })
  it('settings module hash with a section still resolves to settings', () => {
    window.location.hash = '#/settings/general'
    const { result } = renderHook(() => useHashRoute('run'))
    expect(result.current[0]).toBe('settings')
  })

  it('run hash with a template param routes to run and exposes the param', () => {
    window.location.hash = '#/run?template=matrix-triage-quick'
    const { result } = renderHook(() => useHashRoute('run'))
    expect(result.current[0]).toBe('run')
    expect(readHashParams().get('template')).toBe('matrix-triage-quick')
  })
})
