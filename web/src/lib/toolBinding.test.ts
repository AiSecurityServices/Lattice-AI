import { describe, expect, it } from 'vitest'
import { newToolBindingId, toolBindingKey } from './toolBinding'

describe('tool binding helpers', () => {
  it('creates unique ids', () => {
    expect(newToolBindingId()).not.toBe(newToolBindingId())
  })

  it('prefers key and falls back to tool', () => {
    expect(toolBindingKey({ tool: 'nmap', key: 'k1' })).toBe('k1')
    expect(toolBindingKey({ tool: 'nmap' })).toBe('nmap')
  })
})
