import { useEffect, useState, type ReactNode } from 'react'
import { Cpu, Code, DotsThree, Globe, MagnifyingGlass, Network, Plugs, Plus, Play } from '@phosphor-icons/react'
import { cloneTemplate, deleteTemplate, getTemplate, installMarketplace, installStatus, listMarketplace, listTemplates, listToolchainRegistry, renameTemplate, saveTemplate, type MarketplaceModule } from '../api'
import EvolutionRunsDialog from '../components/EvolutionRunsDialog'
import { GenerateTemplateDialog } from '../components/GenerateTemplateDialog'
import TemplateVersionsDrawer from '../components/TemplateVersionsDrawer'
import { Button } from '../components/ui/Button'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'
import { NameDialog } from '../components/ui/NameDialog'
import { t, useLang, type Lang } from '../i18n'
import type { Template } from '../types'

// Matrix metadata lives on the stored template JSON (models.py Template);
// the list endpoint returns id+name only, so the page fans out getTemplate.
// Declared locally: types.ts is owned by the import-wizard workstream.
interface TemplateMeta {
  tags?: string[]
  depth?: string
  target_type?: string
  summary?: string
  name_i18n?: { zh: string; en: string }
  description_i18n?: { zh: string; en: string }
  stages?: { id: string; tools?: { tool: string }[] }[]
}

const TARGET_TYPES = ['web', 'api', 'domain', 'host', 'repo'] as const
const DEPTHS = ['lite', 'standard', 'extensive', 'special'] as const

const TARGET_ICONS: Record<string, ReactNode> = {
  web: <Globe size={13} weight="duotone" />,
  api: <Plugs size={13} weight="duotone" />,
  domain: <Network size={13} weight="duotone" />,
  host: <Cpu size={13} weight="duotone" />,
  repo: <Code size={13} weight="duotone" />,
}

function boundTools(meta: TemplateMeta | undefined): string[] {
  const names = new Set<string>()
  for (const stage of meta?.stages ?? []) {
    for (const binding of stage.tools ?? []) {
      if (binding.tool) names.add(binding.tool)
    }
  }
  return [...names]
}

function marketDescription(m: MarketplaceModule, lang: Lang): string {
  return m.description_i18n?.[lang] ?? m.description
}

function localizedName(name: string, meta: TemplateMeta | undefined, lang: Lang): string {
  return meta?.name_i18n?.[lang] ?? name
}

function localizedSummary(meta: TemplateMeta | undefined, lang: Lang): string {
  return meta?.description_i18n?.[lang] ?? meta?.summary ?? ''
}

export default function TemplatesPage({
  onOpen,
  refreshKey,
  onTemplateUpdated,
}: {
  onOpen: (id: string) => void
  refreshKey: number
  onTemplateUpdated?: () => void
}) {
  const lang = useLang()
  const [templates, setTemplates] = useState<{ id: string; name: string }[]>([])
  const [metaById, setMetaById] = useState<Record<string, TemplateMeta>>({})
  const [installedTools, setInstalledTools] = useState<Set<string>>(new Set())
  const [targetFilter, setTargetFilter] = useState<string>('all')
  const [depthFilter, setDepthFilter] = useState<string>('all')
  const [market, setMarket] = useState<MarketplaceModule[]>([])
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [installError, setInstallError] = useState('')
  const [installDone, setInstallDone] = useState('')
  const [installing, setInstalling] = useState<string | null>(null)
  const [installProgress, setInstallProgress] = useState<Record<string, string> | null>(null)
  const [search, setSearch] = useState('')
  // Single bottom panel slot: opening versions closes suggestions and vice
  // versa — the two drawers used to stack and crush the page.
  const [panel, setPanel] = useState<{ kind: 'versions' | 'suggest'; id: string; name?: string } | null>(null)
  const [menuFor, setMenuFor] = useState<string | null>(null)

  useEffect(() => {
    if (!menuFor) return
    function onPointerDown(event: MouseEvent) {
      if (!(event.target as HTMLElement).closest('.tpl-menu-wrap')) setMenuFor(null)
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setMenuFor(null)
    }
    document.addEventListener('mousedown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [menuFor])

  async function load() {
    const [{ templates: list }, registryView] = await Promise.all([listTemplates(), listToolchainRegistry()])
    setTemplates(list)
    setInstalledTools(new Set(registryView.registry.filter((entry) => entry.installed).map((entry) => entry.name)))
    setMarket((await listMarketplace()).templates)
    const metas = await Promise.all(
      list.map((item) => getTemplate(item.id).then((tpl) => tpl as Template & TemplateMeta).catch(() => null)),
    )
    setMetaById(Object.fromEntries(list.map((item, index) => [item.id, metas[index]]).filter(([, meta]) => meta)))
  }

  useEffect(() => {
    load()
  }, [refreshKey])

  async function create() {
    setError('')
    const t: Template = {
      id: 'untitled-' + Date.now(),
      name: 'Untitled',
      start: 'start',
      stages: [{ id: 'start', name: 'Start', goal: '' }],
      tools: [],
    }
    await saveTemplate(t.id, t)
    load()
  }

  async function install(id: string) {
    setError('')
    setInstallError('')
    setInstallDone('')
    setInstallProgress(null)
    setInstalling(id)
    try {
      const result = await installMarketplace(id)
      if (!result.job_id) {
        setInstallDone(t('toolchain.installed'))
        await load()
        return
      }
      let state = { status: 'installing', results: [] as { name: string; status: string; detail: string }[], error: null as string | null }
      for (let i = 0; i < 600; i++) {
        state = await installStatus(result.job_id)
        setInstallProgress(Object.fromEntries(state.results.map((r) => [r.name, r.status])))
        if (state.status !== 'installing') break
        await new Promise((resolve) => setTimeout(resolve, 1000))
      }
      if (state.status === 'installing') {
        setInstallError(t('tplp.install.timeout'))
        return
      }
      const failed = state.results.filter((r) => r.status === 'failed')
      if (failed.length > 0) {
        setInstallError(
          t('tplp.install.failed')
            .replace('{names}', failed.map((r) => r.name).join(t('tplp.joiner')))
            .replace('{detail}', failed[0].detail),
        )
      } else {
        setInstallDone(t('tplp.install.done'))
      }
    } catch (e) {
      setInstallError(t('tplp.install.failed.reason').replace('{message}', (e as Error).message ?? String(e)))
    } finally {
      setInstalling(null)
      setInstallProgress(null)
      load()
    }
  }

  async function removeConfirmed() {
    if (!confirmingDelete) return
    const id = confirmingDelete
    setConfirmingDelete(null)
    await deleteTemplate(id)
    load()
  }

  async function clone(id: string) {
    await cloneTemplate(id)
    load()
  }

  async function renameConfirmed(name: string) {
    if (!renaming) return
    const id = renaming
    setRenaming(null)
    await renameTemplate(id, name)
    load()
  }

  async function exportTemplate(id: string) {
    const tpl = await getTemplate(id)
    const blob = new Blob([JSON.stringify(tpl, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${id}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const query = search.trim().toLowerCase()
  const filteredTemplates = templates.filter((tpl) => {
    if (!`${tpl.name} ${tpl.id}`.toLowerCase().includes(query)) return false
    const meta = metaById[tpl.id]
    if (targetFilter !== 'all' && (meta?.target_type ?? '') !== targetFilter) return false
    if (depthFilter !== 'all' && (meta?.depth ?? '') !== depthFilter) return false
    return true
  })

  function filterRow(label: string, values: readonly string[], allLabel: string, labelOf: (value: string) => string, active: string, onPick: (value: string) => void) {
    return (
      <div className="tpl-filter-row">
        <span className="tpl-filter-label">{label}</span>
        {[['all', allLabel], ...values.map((v) => [v, labelOf(v)])].map(([value, text]) => (
          <button
            key={value}
            type="button"
            className={`tpl-chip${active === value ? ' active' : ''}`}
            aria-pressed={active === value}
            onClick={() => onPick(value as string)}
          >
            {text}
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="page">
      <div className="template-page">
        <div className="template-main">
          <div className="page-heading">
            <h2 className="page-heading-title">{t('tplp.title')}</h2>
            <div className="page-heading-actions">
              <label className="search-input">
                <MagnifyingGlass size={14} weight="bold" />
                <input className="input" placeholder={t('tplp.search.placeholder')} value={search} onChange={(event) => setSearch(event.target.value)} />
              </label>
              <Button size="sm" icon={<Plus size={15} weight="bold" />} onClick={() => setGenerating(true)}>
                {t('tplp.generate')}
              </Button>
              <Button size="sm" icon={<Plus size={15} weight="bold" />} onClick={create}>
                {t('tplp.create.blank')}
              </Button>
            </div>
          </div>
          {error && <div className="text-danger">{error}</div>}
          {installError && <div className="text-danger">{installError}</div>}
          {installDone && <div className="text-success">{installDone}</div>}

          <div className="tpl-filters" role="group" aria-label={t('tpl.filters.aria')}>
            {filterRow(t('tpl.filters.target'), TARGET_TYPES, t('tpl.target.all'), (v) => t(`tpl.target.${v}`), targetFilter, setTargetFilter)}
            {filterRow(t('tpl.filters.depth'), DEPTHS, t('tpl.depth.all'), (v) => t(`tpl.depth.${v}`), depthFilter, setDepthFilter)}
          </div>

          {filteredTemplates.length === 0 ? (
            <div className="empty">
              <div className="empty-title">{templates.length === 0 ? t('tplp.empty.none') : t('tplp.empty.nomatch')}</div>
              <div className="empty-desc">{templates.length === 0 ? t('tplp.empty.desc') : t('tplp.empty.nomatch.desc')}</div>
            </div>
          ) : (
            <div className="template-grid">
              {filteredTemplates.map((tpl) => {
                const meta = metaById[tpl.id]
                const stageCount = meta?.stages?.length
                const missing = boundTools(meta).filter((name) => !installedTools.has(name))
                return (
                  <div key={tpl.id} className="card template-card">
                    <div className="template-card-title">{localizedName(tpl.name, meta, lang)}</div>
                    {localizedSummary(meta, lang) && <div className="template-card-desc">{localizedSummary(meta, lang)}</div>}
                    <div className="tpl-badges">
                      {meta?.target_type && (
                        <span className="tpl-badge tpl-badge-target">
                          {TARGET_ICONS[meta.target_type]}
                          {t(`tpl.target.${meta.target_type}`)}
                        </span>
                      )}
                      {meta?.depth && <span className={`tpl-badge tpl-depth-${meta.depth}`}>{t(`tpl.depth.${meta.depth}`)}</span>}
                      {(meta?.tags ?? []).slice(0, 3).map((tag) => (
                        <span key={tag} className="tpl-badge tpl-badge-tag">{tag}</span>
                      ))}
                    </div>
                    <div className="template-card-meta">
                      {typeof stageCount === 'number' && <span>{stageCount} {t('tpl.card.stages')}</span>}
                      <span className="tpl-card-id">{tpl.id}</span>
                    </div>
                    {boundTools(meta).length > 0 && (
                      <div className={`tpl-card-tools${missing.length ? ' tpl-tools-missing' : ''}`}>
                        {missing.length === 0
                          ? `✓ ${t('tpl.card.toolsReady')}`
                          : `${t('tpl.card.toolsMissing')}: ${missing.slice(0, 4).join(t('tplp.joiner'))}${missing.length > 4 ? t('tplp.missing.more').replace('{count}', String(missing.length)) : ''}`}
                      </div>
                    )}
                    <div className="template-card-actions">
                      <Button size="sm" variant="secondary" icon={<Play size={13} weight="bold" />} onClick={() => { window.location.hash = `/run?template=${encodeURIComponent(tpl.id)}` }}>
                        {t('tpl.card.run')}
                      </Button>
                      <Button size="sm" onClick={() => onOpen(tpl.id)}>
                        {t('tplp.open')}
                      </Button>
                      <div className="tpl-menu-wrap">
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label={t('tplp.more.aria')}
                          aria-expanded={menuFor === tpl.id}
                          icon={<DotsThree size={15} weight="bold" />}
                          onClick={() => setMenuFor(menuFor === tpl.id ? null : tpl.id)}
                        />
                        {menuFor === tpl.id && (
                          <div className="popover-menu" role="menu">
                            <button role="menuitem" onClick={() => { setMenuFor(null); setPanel({ kind: 'versions', id: tpl.id }) }}>
                              {t('evo.versions.title')}
                            </button>
                            <button role="menuitem" onClick={() => { setMenuFor(null); setPanel({ kind: 'suggest', id: tpl.id, name: tpl.name }) }}>
                              {t('evo.panel.title')}
                            </button>
                            <div className="popover-sep" />
                            <button role="menuitem" onClick={() => { setMenuFor(null); void clone(tpl.id) }}>
                              {t('tplp.clone')}
                            </button>
                            <button role="menuitem" onClick={() => { setMenuFor(null); setRenaming(tpl.id) }}>
                              {t('tplp.rename')}
                            </button>
                            <button role="menuitem" onClick={() => { setMenuFor(null); void exportTemplate(tpl.id) }}>
                              {t('tplp.export')}
                            </button>
                            <div className="popover-sep" />
                            <button role="menuitem" className="danger" onClick={() => { setMenuFor(null); setConfirmingDelete(tpl.id) }}>
                              {t('tplp.delete')}
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <aside className="market-panel">
          <h3>{t('tplp.market.title')}</h3>
          {market.map((m) => (
            <div key={m.id} className="market-item">
              <div className="market-item-title">{m.name_i18n?.[lang] ?? m.name}</div>
              <div className="market-item-desc">{marketDescription(m, lang)}</div>
              {installing === m.id && installProgress && (
                <div className="market-item-note">
                  {t('tplp.installing.progress').replace('{status}', Object.entries(installProgress).map(([name, st]) => `${name}=${st}`).join(t('tplp.joiner')))}
                </div>
              )}
              {(m.needs_tools ?? []).filter((n) => !m.tools_installed?.[n]).length > 0 && (
                <div className="market-item-note">
                  {t('tplp.needs.tools').replace('{names}', (m.needs_tools ?? []).filter((n) => !m.tools_installed?.[n]).join(t('tplp.joiner')))}
                </div>
              )}
              {m.dependencies && (
                <div className="market-item-note">
                  {m.dependencies.runners.length > 0 && <div>{t('tplp.deps.runners').replace('{names}', m.dependencies.runners.join(t('tplp.joiner')))}</div>}
                  {m.dependencies.secrets.length > 0 && <div>{t('tplp.deps.secrets').replace('{names}', m.dependencies.secrets.join(t('tplp.joiner')))}</div>}
                  {m.dependencies.approvals.length > 0 && <div>{t('tplp.deps.approvals').replace('{names}', m.dependencies.approvals.join(t('tplp.joiner')))}</div>}
                </div>
              )}
              <Button size="sm" variant="secondary" disabled={installing === m.id} onClick={() => install(m.id)}>
                {installing === m.id ? t('tplp.installing') : t('toolchain.install')}
              </Button>
            </div>
          ))}
        </aside>
      </div>

      <ConfirmDialog
        open={!!confirmingDelete}
        title={t('tplp.delete.title')}
        description={t('tplp.delete.desc').replace('{id}', confirmingDelete ?? '')}
        confirmLabel={t('tplp.delete')}
        danger
        onConfirm={removeConfirmed}
        onCancel={() => setConfirmingDelete(null)}
      />
      <NameDialog
        open={!!renaming}
        title={t('tplp.rename.title')}
        initialValue={templates.find((item) => item.id === renaming)?.name ?? ''}
        confirmLabel={t('common.save')}
        onConfirm={renameConfirmed}
        onCancel={() => setRenaming(null)}
      />
      <GenerateTemplateDialog
        open={generating}
        onCancel={() => setGenerating(false)}
        onApplied={() => {
          setGenerating(false)
          load()
          onTemplateUpdated?.()
        }}
      />
      {panel?.kind === 'versions' && (
        <TemplateVersionsDrawer templateId={panel.id} onClose={() => setPanel(null)} />
      )}
      {panel?.kind === 'suggest' && (
        <EvolutionRunsDialog
          templateId={panel.id}
          templateName={panel.name ?? ''}
          onClose={() => setPanel(null)}
        />
      )}
    </div>
  )
}
