import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { useHashRoute } from './hooks/useHashRoute'
import { toast } from './lib/toast'
import { ToastHost } from './components/ui/Toast'
import {
  createConversation,
  createProject,
  deleteConversation,
  deleteProject,
  getCurrentProject,
  getTemplate,
  listConversations,
  listProjects,
  listTemplates,
  renameProject,
  saveTemplate,
  switchProject,
  updateConversation,
} from './api'
import type { Project, Session, SessionKind, Template } from './types'
import { t, useLang } from './i18n'
import { AppHeader } from './components/AppHeader'
import { AppSidebar, SIDEBAR_DEFAULT, SIDEBAR_MAX, SIDEBAR_MIN, type ModuleKey } from './components/AppSidebar'
import { AssistantDock } from './components/AssistantDock'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Button } from './components/ui/Button'
import { readLocal, writeLocal } from './lib/storage'
import { timeSuffix } from './lib/format'
import RunPage from './pages/RunPage'

const WorkflowPage = lazy(() => import('./pages/WorkflowPage'))
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const ToolsPage = lazy(() => import('./pages/ToolsPage'))
const SkillsPage = lazy(() => import('./pages/SkillsPage'))
const TemplatesPage = lazy(() => import('./pages/TemplatesPage'))
const AssetsPage = lazy(() => import('./pages/AssetsPage'))
const FindingsPage = lazy(() => import('./pages/FindingsPage'))
const LogsPage = lazy(() => import('./pages/LogsPage'))
const TrashPage = lazy(() => import('./pages/TrashPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))

export default function App() {
  useLang()
  const [active, setActive] = useHashRoute('run')
  const [projects, setProjects] = useState<Project[]>([])
  const [currentProjectId, setCurrentProjectId] = useState('')
  const [collapsed, setCollapsed] = useState(false)
  const [sidebarWidth, setSidebarWidth] = useState(() => Number(readLocal('lattice.sidebarWidth', '')) || SIDEBAR_DEFAULT)
  const [assetVersion, setAssetVersion] = useState(0)
  const [templates, setTemplates] = useState<{ id: string; name: string }[]>([])
  const [activeTemplate, setActiveTemplate] = useState<Template | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [currentSessionId, setCurrentSessionId] = useState('')
  const [workflowSave, setWorkflowSave] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [assetsDirty, setAssetsDirty] = useState(false)
  const [findingsDirty, setFindingsDirty] = useState(false)
  const [headerVisible, setHeaderVisible] = useState(() => readLocal('lattice.ui.header', '1') !== '0')
  // The AI assistant dock starts open on every page; hiding it (sidebar toggle
  // or the dock's close button) persists so it stays hidden until re-opened.
  const [dockVisible, setDockVisible] = useState(() => readLocal('lattice.ui.dock', '1') !== '0')

  const currentProject = useMemo(
    () => projects.find((project) => project.id === currentProjectId),
    [projects, currentProjectId],
  )

  useEffect(() => {
    listProjects().then((result) => {
      setProjects(result.projects)
      setCurrentProjectId(result.current)
    })
  }, [])

  useEffect(() => {
    listTemplates().then(({ templates: list }) => {
      setTemplates(list)
      if (list.length && !activeTemplate) selectTemplate(list[0].id)
    })
  }, [assetVersion])

  useEffect(() => {
    listConversations().then(({ conversations }) => {
      setSessions(conversations)
      const firstTask = conversations.find((s) => s.kind === 'task')
      setCurrentSessionId((prev) =>
        conversations.some((s) => s.id === prev) ? prev : (firstTask ?? conversations[0])?.id ?? '',
      )
    })
  }, [currentProjectId, assetVersion])

  useEffect(() => {
    if (workflowSave !== 'saved') return
    const timer = window.setTimeout(() => setWorkflowSave('idle'), 2000)
    return () => window.clearTimeout(timer)
  }, [workflowSave])

  function resizeSidebar(w: number) {
    const clamped = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, w))
    setSidebarWidth(clamped)
    writeLocal('lattice.sidebarWidth', String(clamped))
  }

  async function selectTemplate(id: string) {
    try {
      setActiveTemplate(await getTemplate(id))
    } catch {
      setActiveTemplate(null)
    }
  }

  function refreshActiveTemplate() {
    if (activeTemplate) void selectTemplate(activeTemplate.id)
  }

  async function selectProject(id: string) {
    if (!id || id === currentProjectId) return
    await switchProject(id)
    setCurrentProjectId(id)
    try {
      const project = await getCurrentProject()
      if (project.current_template_id) await selectTemplate(project.current_template_id)
    } catch {
      // ignore; fall back to first template below
    }
  }

  async function newProject(name: string) {
    if (!name.trim()) return
    try {
      const project = await createProject(name.trim())
      await switchProject(project.id)
      const result = await listProjects()
      setProjects(result.projects)
      setCurrentProjectId(project.id)
    } catch (error) {
      toast(String(error))
    }
  }

  async function renameCurrent(name: string) {
    if (!currentProject || !name.trim()) return
    await renameProject(currentProject.id, name.trim())
    setProjects((await listProjects()).projects)
  }

  async function deleteCurrent() {
    if (!currentProject) return
    if (projects.length <= 1) {
      toast(t('app.keepOneProject'), 'info')
      return
    }
    const other = projects.find((project) => project.id !== currentProject.id)!
    await switchProject(other.id)
    await deleteProject(currentProject.id)
    const result = await listProjects()
    setProjects(result.projects)
    setCurrentProjectId(other.id)
  }

  const titles: Record<ModuleKey, string> = {
    dashboard: t('module.dashboard'),
    run: t('module.run'),
    workflow: t('module.workflow'),
    tools: t('module.tools'),
    skills: t('module.skills'),
    templates: t('module.templates'),
    assets: t('module.assets'),
    findings: t('module.findings'),
    logs: t('module.logs'),
    trash: t('module.trash'),
    settings: t('module.settings'),
  }

  function openInWorkflow(id: string) {
    selectTemplate(id)
    setActive('workflow')
  }

  function selectSession(id: string) {
    setCurrentSessionId(id)
  }

  function navigate(key: ModuleKey) {
    if (key === 'assets') setAssetsDirty(false)
    if (key === 'findings') setFindingsDirty(false)
    setActive(key)
  }

  async function createSession(kind: SessionKind, name?: string) {
    // Timestamped default names keep the session list scannable when every
    // conversation would otherwise be called the same generic label.
    const baseName = name ?? (kind === 'assistant' ? t('session.assistant') : t('session.task'))
    const conv = await createConversation({
      kind,
      name: name ? baseName : `${baseName} ${timeSuffix()}`,
      template_id: activeTemplate?.id ?? '',
      model: '',
      reasoning_effort: '',
    })
    setSessions((prev) => [...prev, conv])
    setCurrentSessionId(conv.id)
    return conv
  }

  async function createSessionWithPatch(kind: SessionKind, patch?: Partial<Session>) {
    const conv = await createSession(kind)
    if (!patch) return conv
    const updated = await updateConversation(conv.id, patch)
    setSessions((prev) => prev.map((s) => (s.id === updated.id ? updated : s)))
    return updated
  }

  async function saveActiveTemplate() {
    if (!activeTemplate || workflowSave === 'saving') return
    setWorkflowSave('saving')
    try {
      await saveTemplate(activeTemplate.id, activeTemplate)
      setWorkflowSave('saved')
    } catch (error) {
      setWorkflowSave('idle')
      toast(String(error))
    }
  }

  async function renameSession(id: string, name: string) {
    const conv = await updateConversation(id, { name })
    setSessions((prev) => prev.map((s) => (s.id === conv.id ? conv : s)))
  }

  async function deleteSession(id: string) {
    await deleteConversation(id)
    setSessions((prev) => prev.filter((s) => s.id !== id))
    setCurrentSessionId((prev) => (prev === id ? '' : prev))
  }

  function updateSession(id: string, patch: Partial<Session>) {
    updateConversation(id, patch).then((conv) => {
      setSessions((prev) => prev.map((s) => (s.id === conv.id ? conv : s)))
    })
  }

  const assistantSession =
    sessions.find((s) => s.id === currentSessionId && s.kind === 'assistant') ??
    sessions.find((s) => s.kind === 'assistant') ??
    null
  // 资产/发现页按“任务会话”作用域展示：聊天（assistant）会话不产生侦察结果，
  // 选中聊天会话时不能把这两页静默清空。跟随当前选中的任务会话，无则回退到第一个。
  const taskSession = useMemo(() => {
    const current = sessions.find((s) => s.id === currentSessionId)
    if (current?.kind === 'task') return current
    return sessions.find((s) => s.kind === 'task') ?? null
  }, [sessions, currentSessionId])

  const templateSwitcher = (
    <label className="app-template-context">
      <span className="app-template-label">{t('app.currentTemplate')}</span>
      <select className="select app-template-select" aria-label={t('app.currentTemplate')} value={activeTemplate?.id ?? ''} onChange={(e) => selectTemplate(e.target.value)}>
        {templates.length === 0 && <option value="">{t('app.noTemplate')}</option>}
        {templates.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
    </label>
  )

  function toggleHeader() {
    setHeaderVisible((value) => {
      writeLocal('lattice.ui.header', value ? '0' : '1')
      return !value
    })
  }

  function toggleDock() {
    setDockVisible((value) => {
      writeLocal('lattice.ui.dock', value ? '0' : '1')
      return !value
    })
  }

  return (
    <div className="app">
      <ToastHost />
      <AppSidebar
        projects={projects}
        currentProjectId={currentProjectId}
        active={active}
        collapsed={collapsed}
        width={sidebarWidth}
        onToggle={() => setCollapsed((value) => !value)}
        onResize={resizeSidebar}
        onSelectProject={selectProject}
        onNavigate={navigate}
        assetsDirty={assetsDirty}
        findingsDirty={findingsDirty}
        onCreateSession={createSession}
        headerVisible={headerVisible}
        dockVisible={dockVisible}
        onToggleHeader={toggleHeader}
        onToggleDock={toggleDock}
        onProjectAction={(action, name) => {
          if (action === 'create' && name) void newProject(name)
          if (action === 'rename' && name) void renameCurrent(name)
          if (action === 'delete') void deleteCurrent()
        }}
      />
      <main className="main" key={currentProjectId}>
        {headerVisible && (
          <AppHeader
            breadcrumb={currentProject?.name ?? t('module.project')}
            // Content pages carry their own page-heading; repeating the module
            // name here doubles the tallest element on every screen.
            title={active === 'run' || active === 'workflow' ? titles[active] : ''}
            context={templateSwitcher}
            actions={
              active === 'workflow' ? (
                <Button
                  size="sm"
                  loading={workflowSave === 'saving'}
                  disabled={!activeTemplate || workflowSave === 'saving'}
                  onClick={() => void saveActiveTemplate()}
                >
                  {t('common.save')}
                </Button>
              ) : undefined
            }
          />
        )}
        <div className="page" style={{ display: active === 'run' ? 'flex' : 'none' }}>
          <ErrorBoundary>
            <RunPage
            template={activeTemplate}
            sessions={sessions}
            currentSessionId={currentSessionId}
            onSelectSession={selectSession}
            onCreateSession={createSessionWithPatch}
            onRenameSession={renameSession}
            onDeleteSession={deleteSession}
            onUpdateSession={updateSession}
            onOpenSettings={() => setActive('settings')}
            projectName={currentProject?.name}
            pageTitle={titles.run}
            onActionComplete={() => setAssetVersion((value) => value + 1)}
            onRunComplete={() => {
              setAssetsDirty(true)
              setFindingsDirty(true)
            }}
            onTemplateUpdated={refreshActiveTemplate}
            onTemplateCreated={openInWorkflow}
            />
          </ErrorBoundary>
        </div>
        <ErrorBoundary>
          <Suspense fallback={<div className="muted">{t('common.loading')}</div>}>
            {active === 'dashboard' && (
              <DashboardPage refreshKey={assetVersion} sessionId={currentSessionId} onNavigate={navigate} />
            )}
            {active === 'workflow' && <WorkflowPage template={activeTemplate} onTemplateChange={setActiveTemplate} />}
            {active === 'tools' && <ToolsPage activeTemplate={activeTemplate} refreshKey={assetVersion} onTemplateUpdated={refreshActiveTemplate} />}
            {active === 'skills' && <SkillsPage activeTemplate={activeTemplate} refreshKey={assetVersion} onTemplateUpdated={refreshActiveTemplate} />}
            {active === 'templates' && <TemplatesPage onOpen={openInWorkflow} refreshKey={assetVersion} onTemplateUpdated={refreshActiveTemplate} />}
            {active === 'assets' && <AssetsPage refreshKey={assetVersion} onNavigate={navigate} sessionId={taskSession?.id ?? ''} sessionName={taskSession?.name ?? ''} />}
            {active === 'findings' && <FindingsPage refreshKey={assetVersion} onNavigate={navigate} sessionId={taskSession?.id ?? ''} sessionName={taskSession?.name ?? ''} />}
            {active === 'logs' && <LogsPage refreshKey={assetVersion} />}
            {active === 'trash' && <TrashPage refreshKey={assetVersion} onRestored={() => setAssetVersion((value) => value + 1)} />}
            {active === 'settings' && <SettingsPage />}
          </Suspense>
        </ErrorBoundary>
        {active !== 'run' && dockVisible && (
          <AssistantDock
            session={assistantSession}
            onCreate={() => createSession('assistant', `${titles[active]}${t('module.chat')}`)}
            onUpdate={(patch) => {
              if (assistantSession) updateSession(assistantSession.id, patch)
            }}
            onActionComplete={() => setAssetVersion((value) => value + 1)}
          />
        )}
      </main>
    </div>
  )
}
