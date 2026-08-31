import { describe, expect, it } from 'vitest'
import {
  isBlockedScope,
  validateCidr,
  validateDomain,
  validateIp,
  validatePort,
  validateUrlPrefix,
} from './scopeValidate'

describe('scopeValidate', () => {
  it('accepts valid domain', () => {
    expect(validateDomain('example.com')).toEqual({ valid: true })
  })
  it('rejects localhost and blocked domains', () => {
    expect(validateDomain('localhost').valid).toBe(false)
    expect(validateDomain('x.gov').valid).toBe(false)
  })
  it('rejects malformed domain', () => {
    expect(validateDomain('not a domain').valid).toBe(false)
  })
  it('validates ipv4 and ipv6', () => {
    expect(validateIp('203.0.113.10').valid).toBe(true)
    expect(validateIp('2001:db8::1').valid).toBe(true)
    expect(validateIp('999.1.1.1').valid).toBe(false)
  })
  it('validates cidr', () => {
    expect(validateCidr('203.0.113.0/24').valid).toBe(true)
    expect(validateCidr('203.0.113.0/33').valid).toBe(false)
  })
  it('validates port range', () => {
    expect(validatePort('443').valid).toBe(true)
    expect(validatePort('0').valid).toBe(false)
    expect(validatePort('65536').valid).toBe(false)
  })
  it('validates url prefix', () => {
    expect(validateUrlPrefix('https://example.com/api/').valid).toBe(true)
    expect(validateUrlPrefix('ftp://x').valid).toBe(false)
  })
  it('detects blocked scope', () => {
    expect(isBlockedScope('localhost')).toBe(true)
    expect(isBlockedScope('example.com')).toBe(false)
  })
})
