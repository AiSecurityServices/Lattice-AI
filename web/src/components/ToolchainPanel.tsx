import { useCallback, useEffect, useState } from 'react'
import { ArrowsClockwise, Warning } from '@phosphor-icons/react'
import { t, useLang } from '../i18n'
import { Button } from './ui/Button'
import { getToolchainInstallStatus, installToolchain, listToolchainRegistry } from '../api'
import type { ToolchainRegistryEntry } from '../types'

/** Evaluated at render time so the danger tier labels follow language switches. */
function dangerLabel(value: string): string {
  const labels: Record<string, string> = {
    passive: t('tcp.danger.passive'),
    active: t('tcp.danger.active'),
    aggressive: t('tcp.danger.aggressive'),
  }
  return labels[value] ?? value
}

/** Registry-driven install panel (T-U4): the 12 real tools with install
 * state, version and one-click install for auto-mode entries. */
export function ToolchainPanel({ onChanged }: { onChanged?: () => void }) {
  useLang()
  const [entries, setEntries] = useState<ToolchainRegistryEntry[]>([])
  const [busyTool, setBusyTool] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const result = await listToolchainRegistry()
      setEntries(result.registry)
      setError('')
    } catch (err) {
      setError(String(err))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function install(name: string) {
    setBusyTool(name)
    setError('')
    try {
      const { job_id: jobId } = await installToolchain([name])
      for (let i = 0; i < 200; i++) {
        const status = await getToolchainInstallStatus(jobId)
        if (status.status !== 'installing') {
          const result = status.results?.find((r: { name: string }) => r.name === name)
          if (result && result.status !== 'installed' && result.status !== 'already_installed') {
            setError(result.detail || t('tcp.installFailed'))
          }
          break
        }
        await new Promise((resolve) => setTimeout(resolve, 1000))
      }
    } catch (err) {
      setError(String(err))
    } finally {
      setBusyTool('')
      load()
      onChanged?.()
    }
  }

  return (
    <div className="asset-group">
      <div className="section-toolbar">
        <h4 className="section-label">{t('tcp.title')}</h4>
        <Button size="sm" variant="secondary" onClick={() => load()} aria-label={t('tcp.refreshAria')}>
          <ArrowsClockwise size={13} weight="bold" /> {t('tcp.refresh')}
        </Button>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: '4px 0 8px' }}>
        {t('tcp.desc')}
      </p>
      {error && (
        <div className="tag warning" style={{ marginBottom: 8, display: 'inline-block' }}>
          <Warning size={12} weight="bold" /> {error}
        </div>
      )}
      <div className="tool-grid">
        {entries.map((entry) => (
          <div key={entry.name} className="card tool-card">
            <div className="tool-card-head">
              <div className="tool-card-title">{entry.name}</div>
              <span className={`tag ${entry.installed ? 'success' : 'warning'}`}>
                {entry.installed ? t('toolchain.installed') : entry.install_mode === 'manual' ? t('tcp.manualRequired') : t('tcp.notInstalled')}
              </span>
            </div>
            <div className="card-desc">{entry.notes}</div>
            <div className="card-tags">
              <span className="tag">{entry.category}</span>
              <span className={`tag ${entry.danger === 'passive' ? '' : 'warning'}`}>
                {dangerLabel(entry.danger)}
              </span>
              <span className="tag">{entry.output_format}/{entry.parse_level}</span>
              {entry.installed && entry.version && <span className="tag success">v{entry.version}</span>}
              {entry.license && <span className="tag">{entry.license}</span>}
            </div>
            <div className="asset-card-actions">
              {!entry.installed && entry.install_mode === 'auto' && (
                <Button size="sm" variant="primary" loading={busyTool === entry.name} onClick={() => install(entry.name)}>
                  {busyTool === entry.name ? t('tcp.installing') : t('tcp.installOne')}
                </Button>
              )}
              {!entry.installed && entry.install_mode === 'manual' && (
                <span className="muted" style={{ fontSize: 12 }}>{entry.install_manual}</span>
              )}
              {entry.installed && !entry.version && <span className="muted" style={{ fontSize: 12 }}>{t('tcp.versionUnknown')}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
