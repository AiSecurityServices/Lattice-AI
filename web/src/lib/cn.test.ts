import { describe, expect, it } from 'vitest'
import { cn } from './cn'

describe('cn', () => {
  it('joins truthy values', () => {
    expect(cn('btn', 'btn-primary')).toBe('btn btn-primary')
  })

  it('drops falsey values', () => {
    expect(cn('btn', false, null, undefined, 'active')).toBe('btn active')
  })
})
