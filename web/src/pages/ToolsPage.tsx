import { useEffect, useState } from 'react'
import { Cpu, MagnifyingGlass, TerminalWindow } from '@phosphor-icons/react'
import { deleteRecipe, listGroups, listTools, runTool, setGroupMembers, updateTool, type GroupsPayload } from '../api'
import { AssetGroups } from '../components/AssetGroups'
import ImportWizard from '../components/ImportWizard'
import { t, useLang } from '../i18n'
import { ToolchainPanel } from '../components/ToolchainPanel'
import ToolEditor from '../components/ToolEditor'
import { ApplyToWorkflowDialog } from '../components/ui/ApplyToWorkflowDialog'
import { Button } from '../components/ui/Button'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'
import { SegmentedControl } from '../components/ui/SegmentedControl'
import type { Template, Tool } from '../types'

export default function ToolsPage({
  activeTemplate,
  refreshKey,
  onTemplateUpdated,
}: {
  activeTemplate: Template | null
  refreshKey: number
  onTemplateUpdated?: () => void
}) {
  useLang()
  const [tools, setTools] = useState<Tool[]>([])
  const [groups, setGroups] = useState<GroupsPayload>({ tool_groups: [], skill_groups: [] })
  const [editing, setEditing] = useState<Tool | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [capabilityFilter, setCapabilityFilter] = useState<string>('')
  const [usageFilter, setUsageFilter] = useState<string>('')
  const [applying, setApplying] = useState<{ kind: 'tool'; items: string[] } | null>(null)
  const [view, setView] = useState<'assets' | 'groups'>('assets')
  const [wizardOpen, setWizardOpen] = useState(false)

  async function load() {
    const [toolResult, groupResult] = await Promise.all([listTools(), listGroups()])
    setTools(toolResult.tools)
    setGroups(groupResult)
  }

  useEffect(() => {
    load()
  }, [refreshKey])

  function requestRemove(name: string) {
    setConfirming(name)
  }

  async function removeConfirmed() {
    if (!confirming) return
    const name = confirming
    setConfirming(null)
    await deleteRecipe(name)
    load()
  }

  async function saveEdit(tool: Tool) {
    await updateTool(tool.name, tool)
    setEditing(null)
    load()
  }

  async function testTool(tool: Tool, args: Record<string, unknown>) {
    return await runTool(tool, args)
  }

  async function addToolToGroup(name: string, groupId: string) {
    const group = groups.tool_groups.find((g) => g.id === groupId)
    if (!group) return
    const members = group.members.includes(name) ? group.members : [...group.members, name]
    await setGroupMembers('tool', groupId, members)
    setGroups(await listGroups())
  }

  const templateTools = activeTemplate?.tools ?? []
  const query = search.trim().toLowerCase()
  const filteredTools = tools.filter((tool) => {
    const text = `${tool.name} ${tool.description ?? ''}`.toLowerCase()
    const matchesQuery = !query || text.includes(query)
    const matchesCapability = !capabilityFilter || (tool.capability ?? 'other') === capabilityFilter
    const matchesUsage = !usageFilter || (tool.usage ?? 'cli') === usageFilter
    return matchesQuery && matchesCapability && matchesUsage
  })

  return (
    <div className="page">
      <div className="page-heading">
        <h2 className="page-heading-title">{t('tools.title')}</h2>
        <div className="page-heading-actions">
          <SegmentedControl
            options={[
              { value: 'assets', label: t('tools.tab.tools') },
              { value: 'groups', label: t('tools.tab.groups') },
            ]}
            value={view}
            onChange={(value) => setView(value)}
            ariaLabel={t('tools.viewAria')}
          />
          <select className="select" value={capabilityFilter} onChange={(e) => setCapabilityFilter(e.target.value)} aria-label={t('tools.capabilityAria')}>
            <option value="">{t('tools.capabilityAll')}</option>
            <option value="recon">{t('tools.cap.recon')}</option>
            <option value="vuln">{t('tools.cap.vuln')}</option>
            <option value="fuzz">{t('tools.cap.fuzz')}</option>
            <option value="other">{t('tools.cap.other')}</option>
          </select>
          <select className="select" value={usageFilter} onChange={(e) => setUsageFilter(e.target.value)} aria-label={t('tools.usageAria')}>
            <option value="">{t('tools.usageAll')}</option>
            <option value="builtin">{t('tools.builtin')}</option>
            <option value="cli">CLI</option>
            <option value="mcp">MCP</option>
            <option value="http_api">HTTP API</option>
          </select>
          <Button size="sm" variant="primary" onClick={() => setWizardOpen(true)}>{t('imp.wizard.title')}</Button>
          <label className="search-input">
            <MagnifyingGlass size={14} weight="bold" />
            <input className="input" placeholder={t('tools.searchPlaceholder')} value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
          <span className="muted page-heading-count">{t('tools.count').replace('{count}', String(tools.length))}</span>
        </div>
      </div>

      <div className="page-body">
        <ToolchainPanel onChanged={load} />

        {editing && (
          <div className="card-gap">
            <ToolEditor tool={editing} onSave={saveEdit} onCancel={() => setEditing(null)} onTest={testTool} />
          </div>
        )}

        {templateTools.length > 0 && (
          <div className="asset-group">
            <h4 className="section-label">{t('tools.templateTools')}</h4>
            <div className="tool-grid">
              {templateTools.map((tool) => (
                <div key={tool.name} className="card tool-card">
                  <div className="tool-card-head">
                    <div className="tool-card-title">
                      <span className="card-icon" aria-hidden>
                        {tool.runner === 'builtin' ? <Cpu size={15} weight="bold" /> : <TerminalWindow size={15} weight="bold" />}
                      </span>
                      {tool.name}
                    </div>
                  </div>
                  <div className="card-desc">{tool.description}</div>
                  <div className="card-tags">
                    <span className="tag">{tool.runner}</span>
                    <span className="tag">{tool.approval ?? 'allow'}</span>
                    {tool.builtin && <span className="tag">{t('tools.builtin')}</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {view === 'groups' ? (
          <AssetGroups
            kind="tool"
            groups={groups.tool_groups}
            assets={tools}
            onGroupsChange={(toolGroups) => setGroups((prev) => ({ ...prev, tool_groups: toolGroups }))}
            onApply={(items) => setApplying({ kind: 'tool', items })}
          />
        ) : (
          <div className="asset-group">
            <div className="section-toolbar">
              <h4 className="section-label">{t('tools.globalTools')}</h4>
            </div>
            {tools.length === 0 ? (
              <div className="empty">
                <div className="empty-title">{t('tools.emptyTitle')}</div>
                <div className="empty-desc">{t('tools.emptyDesc')}</div>
              </div>
            ) : (
              <div className="tool-grid global-tool-grid">
                {filteredTools.map((tool) => (
                  <div key={tool.name} className="card tool-card">
                    <div className="tool-card-head">
                      <div className="tool-card-title">
                        <span className="card-icon" aria-hidden>
                          {tool.runner === 'builtin' ? <Cpu size={15} weight="bold" /> : <TerminalWindow size={15} weight="bold" />}
                        </span>
                        {tool.name}
                      </div>
                      {!tool.builtin && (
                        <div className="card-actions">
                          <Button size="sm" onClick={() => setEditing(tool)}>
                            {t('tools.edit')}
                          </Button>
                          <Button size="sm" variant="danger" onClick={() => requestRemove(tool.name)}>
                            {t('tools.delete')}
                          </Button>
                        </div>
                      )}
                    </div>
                    <div className="card-desc">{tool.description}</div>
                    <div className="card-tags">
                      <span className="tag">{tool.runner}</span>
                      <span className="tag">{tool.approval ?? 'allow'}</span>
                      {tool.builtin && <span className="tag">{t('tools.builtin')}</span>}
                      <span className={`tag ${(tool.available ?? true) ? 'success' : 'warning'}`}>
                        {(tool.available ?? true) ? t('toolchain.installed') : t('tools.notInstalled')}
                      </span>
                      {(tool.secret_fields ?? []).map((s) => (
                        <span key={s} className="tag warning">
                          {t('tools.secretTag').replace('{name}', s)}
                        </span>
                      ))}
                    </div>
                    <div className="asset-card-actions">
                      {(tool.available ?? true) && (
                        <>
                          <select className="select" value="" aria-label={t('tools.addToGroup')} onChange={(event) => addToolToGroup(tool.name, event.target.value)}>
                            <option value="" disabled>
                              {t('tools.addToGroup')}
                            </option>
                            {groups.tool_groups.map((g) => (
                              <option key={g.id} value={g.id}>
                                {g.name}
                              </option>
                            ))}
                          </select>
                          <Button size="sm" variant="secondary" onClick={() => setApplying({ kind: 'tool', items: [tool.name] })}>
                            {t('tools.useInWorkflow')}
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <ApplyToWorkflowDialog
        open={!!applying}
        kind={applying?.kind ?? 'tool'}
        items={applying?.items ?? []}
        template={activeTemplate}
        onCancel={() => setApplying(null)}
        onApplied={() => {
          setApplying(null)
          onTemplateUpdated?.()
        }}
      />

      <ConfirmDialog
        open={!!confirming}
        title={t('tools.deleteConfirmTitle')}
        description={t('tools.deleteConfirmDesc').replace('{name}', String(confirming))}
        confirmLabel={t('tools.delete')}
        danger
        onConfirm={removeConfirmed}
        onCancel={() => setConfirming(null)}
      />
      {wizardOpen && (
        <ImportWizard
          onClose={() => setWizardOpen(false)}
          onImported={() => load()}
        />
      )}
    </div>
  )
}
