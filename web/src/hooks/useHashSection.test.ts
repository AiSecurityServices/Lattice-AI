import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useHashSection } from './useHashSection'

describe('useHashSection', () => {
  beforeEach(() => {
    window.location.hash = ''
  })
  it('defaults when no hash', () => {
    const { result } = renderHook(() => useHashSection('llm'))
    expect(result.current[0]).toBe('llm')
  })
  it('reads a valid hash', () => {
    window.location.hash = '#/settings/scope'
    const { result } = renderHook(() => useHashSection('llm'))
    expect(result.current[0]).toBe('scope')
  })
  it('falls back on invalid hash', () => {
    window.location.hash = '#/settings/bogus'
    const { result } = renderHook(() => useHashSection('llm'))
    expect(result.current[0]).toBe('llm')
  })
  it('navigate writes the hash', () => {
    const { result } = renderHook(() => useHashSection('llm'))
    act(() => result.current[1]('general'))
    expect(window.location.hash).toBe('#/settings/general')
    expect(result.current[0]).toBe('general')
  })
})
