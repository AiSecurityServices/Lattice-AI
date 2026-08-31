import { useEffect, useState } from 'react'
import { Wrench } from '@phosphor-icons/react'
import { getToolchainInstallStatus, installToolchain, listToolchain } from '../../api'
import type { ToolchainInfo } from '../../types'
import { Button } from '../ui/Button'
import { t, useLang } from '../../i18n'

export function ToolchainSection() {
  useLang()
  const [tools, setTools] = useState<ToolchainInfo[]>([])
  const [installing, setInstalling] = useState<string[]>([])

  useEffect(() => {
    listToolchain().then((r) => setTools(r.tools)).catch(() => setTools([]))
  }, [])

  async function install(name: string) {
    setInstalling((prev) => [...prev, name])
    try {
      const { job_id } = await installToolchain([name])
      await poll(job_id)
      const r = await listToolchain()
      setTools(r.tools)
    } finally {
      setInstalling((prev) => prev.filter((n) => n !== name))
    }
  }

  async function poll(jobId: string) {
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 1200))
      const state = await getToolchainInstallStatus(jobId)
      if (state.status === 'done' || state.status === 'error') return
    }
  }

  return (
    <section className="settings-section card">
      <div className="section-card-head">
        <span className="section-card-icon" aria-hidden>
          <Wrench size={17} weight="bold" />
        </span>
        <div className="section-card-text">
          <h3 className="section-card-title">{t('toolchain.title')}</h3>
          <p className="section-card-desc">{t('toolchain.desc')}</p>
        </div>
      </div>
      <div className="section-card-body">
        {tools.length === 0 && <p className="muted">{t('toolchain.empty')}</p>}
        {tools.map((tool) => (
          <div className="toolchain-row" key={tool.name}>
            <span className="toolchain-name">{tool.name}</span>
            <span className={`toolchain-status ${tool.available ? 'ok' : 'warn'}`}>{tool.available ? t('toolchain.installed') : t('toolchain.missing')}</span>
            {!tool.available && (
              <Button size="sm" variant="secondary" loading={installing.includes(tool.name)} onClick={() => void install(tool.name)}>
                {installing.includes(tool.name) ? t('toolchain.installing') : t('toolchain.install')}
              </Button>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
