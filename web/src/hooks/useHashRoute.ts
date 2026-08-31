import { useEffect, useState } from 'react'
import { MODULES, type ModuleKey } from '../components/AppSidebar'

const KEYS = MODULES.map((m) => m.key)

function currentFromHash(): ModuleKey | null {
  const m = window.location.hash.match(/^#\/([a-z]+)/)
  if (!m) return null
  const key = m[1] as ModuleKey
  return KEYS.includes(key) ? key : null
}

/** Query params of the current hash route: `#/run?template=x` -> get('template')='x'.
 * Pages deep-link parameters this way without touching the app-level router. */
export function readHashParams(): URLSearchParams {
  const m = window.location.hash.match(/\?(.*)$/)
  return new URLSearchParams(m ? m[1] : '')
}

/** Hash-based routing for the top-level modules: `#/run`, `#/findings`, ...
 * Deep-linkable, refresh-safe, back/forward aware — and packaging-friendly
 * since no server-side fallback is needed. The settings page owns its
 * sub-hash (`#/settings/<section>`) via useHashSection. */
export function useHashRoute(defaultKey: ModuleKey) {
  const [key, setKey] = useState<ModuleKey>(() => currentFromHash() ?? defaultKey)
  useEffect(() => {
    const onHash = () => setKey(currentFromHash() ?? defaultKey)
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [defaultKey])
  const navigate = (next: ModuleKey) => {
    window.location.hash = `/${next}`
    setKey(next)
  }
  return [key, navigate] as const
}
