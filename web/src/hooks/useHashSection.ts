import { useEffect, useState } from 'react'
import type { SettingsSectionId } from '../settingsections'

const ALL: SettingsSectionId[] = ['llm', 'scope', 'plan', 'toolchain', 'general']

function currentFromHash(): SettingsSectionId | null {
  const m = window.location.hash.match(/^#\/settings\/([a-z]+)$/)
  if (!m) return null
  const id = m[1] as SettingsSectionId
  return ALL.includes(id) ? id : null
}

export function useHashSection(defaultId: SettingsSectionId) {
  const [id, setId] = useState<SettingsSectionId>(() => currentFromHash() ?? defaultId)
  useEffect(() => {
    const onHash = () => {
      // Bare `#/settings` (module-level navigation) keeps the current section
      // instead of resetting it to the default.
      if (/^#\/settings\/?$/.test(window.location.hash)) return
      setId(currentFromHash() ?? defaultId)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [defaultId])
  const navigate = (next: SettingsSectionId) => {
    window.location.hash = `/settings/${next}`
    setId(next)
  }
  return [id, navigate] as const
}
