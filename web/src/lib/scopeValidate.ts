import { t } from '../i18n'

export interface ScopeValidation {
  valid: boolean
  reason?: string
}

const BLOCKED_SUFFIXES = ['.gov', '.mil', '.gouv.fr', '.mod.uk']

function isValidIpv4(v: string): boolean {
  const parts = v.split('.')
  if (parts.length !== 4) return false
  return parts.every((p) => /^\d{1,3}$/.test(p) && Number(p) >= 0 && Number(p) <= 255)
}

function isValidIpv6(v: string): boolean {
  return v.includes(':') && /^[0-9a-f:]+$/i.test(v)
}

export function validateDomain(value: string): ScopeValidation {
  const v = value.trim().toLowerCase()
  if (!v) return { valid: false, reason: t('sv.domainEmpty') }
  if (v === 'localhost' || v.endsWith('.localhost')) return { valid: false, reason: t('sv.localhostBlocked') }
  if (BLOCKED_SUFFIXES.some((s) => v.endsWith(s))) return { valid: false, reason: t('sv.domainBlocked') }
  const re = /^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$/
  return re.test(v) ? { valid: true } : { valid: false, reason: t('sv.domainInvalid') }
}

export function validateIp(value: string): ScopeValidation {
  const v = value.trim()
  if (isValidIpv4(v) || isValidIpv6(v)) return { valid: true }
  return { valid: false, reason: t('sv.ipInvalid') }
}

export function validateCidr(value: string): ScopeValidation {
  const [ip, prefix] = value.trim().split('/')
  if (!ip || prefix === undefined) return { valid: false, reason: t('sv.cidrMissingPrefix') }
  const ipv4 = isValidIpv4(ip)
  if (!ipv4 && !isValidIpv6(ip)) return { valid: false, reason: t('sv.cidrInvalid') }
  if (!/^\d{1,3}$/.test(prefix)) return { valid: false, reason: t('sv.cidrPrefixNumeric') }
  const p = Number(prefix)
  const max = ipv4 ? 32 : 128
  if (p < 0 || p > max) return { valid: false, reason: t('sv.cidrPrefixRange').replace('{max}', String(max)) }
  return { valid: true }
}

export function validatePort(value: string): ScopeValidation {
  const n = Number(value.trim())
  if (!Number.isInteger(n) || n < 1 || n > 65535) return { valid: false, reason: t('sv.portRange') }
  return { valid: true }
}

export function validateUrlPrefix(value: string): ScopeValidation {
  const v = value.trim()
  if (!/^https?:\/\/.+/.test(v)) return { valid: false, reason: t('sv.urlPrefixInvalid') }
  return { valid: true }
}

export function isBlockedScope(value: string): boolean {
  const v = value.trim().toLowerCase()
  if (v === 'localhost' || v.endsWith('.localhost')) return true
  return BLOCKED_SUFFIXES.some((s) => v.endsWith(s))
}
