export type ThemePref = 'system' | 'light' | 'dark'
export type ResolvedTheme = 'light' | 'dark'

let currentPref: ThemePref = 'system'
let detachSystemListener: (() => void) | null = null

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)').matches
    : false
}

export function resolveTheme(pref: ThemePref): ResolvedTheme {
  if (pref === 'light' || pref === 'dark') return pref
  return systemPrefersDark() ? 'dark' : 'light'
}

function attachSystemListener() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function' || detachSystemListener) {
    return
  }
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  const onChange = () => {
    if (currentPref === 'system') applyTheme('system')
  }
  mq.addEventListener('change', onChange)
  detachSystemListener = () => mq.removeEventListener('change', onChange)
}

export function applyTheme(pref: ThemePref) {
  currentPref = pref
  document.documentElement.dataset.theme = resolveTheme(pref)
  if (pref === 'system') {
    attachSystemListener()
  } else if (detachSystemListener) {
    detachSystemListener()
    detachSystemListener = null
  }
}

export function getThemePref(): ThemePref {
  return currentPref
}
