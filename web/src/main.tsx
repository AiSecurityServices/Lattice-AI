import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { setLang } from './i18n'
import { applyTheme } from './theme'
import { readLocal } from './lib/storage'

async function applyStoredPreferences() {
  try {
    const token = readLocal('lattice.token', '')
    const res = await fetch('/api/preferences', token ? { headers: { 'X-Lattice-Token': token } } : undefined)
    const prefs = await res.json()
    applyTheme(prefs.theme ?? 'light')
    setLang(prefs.language === 'zh' ? 'zh' : 'en')
  } catch {
    // 默认浅色 / 英文
  }
}
void applyStoredPreferences()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
