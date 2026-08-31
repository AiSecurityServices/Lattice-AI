import type { Project, SessionKind } from '../types'
import { useRef, type ReactNode } from 'react'
import { cn } from '../lib/cn'
import { t, useLang } from '../i18n'
import { ProjectMenu } from './ProjectMenu'
import { ChatCircle, ChatCircleDots, Crosshair, Eye, EyeSlash, Gauge, GearSix, GitBranch, Lightbulb, ListMagnifyingGlass, Network, ShieldCheck, SquaresFour, Trash, Wrench } from '@phosphor-icons/react'
import { LatticeLogo } from './LatticeLogo'

export type ModuleKey = 'dashboard' | 'run' | 'workflow' | 'tools' | 'skills' | 'templates' | 'assets' | 'findings' | 'logs' | 'trash' | 'settings'

export const SIDEBAR_DEFAULT = 232
export const SIDEBAR_MIN = 180
export const SIDEBAR_MAX = 480

export const MODULES: Array<{ key: ModuleKey; label: string; icon: ReactNode }> = [
  { key: 'dashboard', get label(): string { return t('module.dashboard') }, icon: <Gauge size={17} weight="duotone" /> },
  { key: 'run', get label(): string { return t('module.run') }, icon: <Crosshair size={17} weight="duotone" /> },
  { key: 'workflow', get label(): string { return t('module.workflow') }, icon: <GitBranch size={17} weight="duotone" /> },
  { key: 'tools', get label(): string { return t('module.tools') }, icon: <Wrench size={17} weight="duotone" /> },
  { key: 'skills', get label(): string { return t('module.skills') }, icon: <Lightbulb size={17} weight="duotone" /> },
  { key: 'templates', get label(): string { return t('module.templates') }, icon: <SquaresFour size={17} weight="duotone" /> },
  { key: 'assets', get label(): string { return t('module.assets') }, icon: <Network size={17} weight="duotone" /> },
  { key: 'findings', get label(): string { return t('module.findings') }, icon: <ShieldCheck size={17} weight="duotone" /> },
  { key: 'logs', get label(): string { return t('module.logs') }, icon: <ListMagnifyingGlass size={17} weight="duotone" /> },
  { key: 'trash', get label(): string { return t('module.trash') }, icon: <Trash size={17} weight="duotone" /> },
  { key: 'settings', get label(): string { return t('module.settings') }, icon: <GearSix size={17} weight="duotone" /> },
]

export function AppSidebar({
  projects,
  currentProjectId,
  active,
  collapsed,
  width = SIDEBAR_DEFAULT,
  onToggle,
  onResize,
  onSelectProject,
  onNavigate,
  onCreateSession,
  onProjectAction,
  assetsDirty,
  findingsDirty,
  headerVisible,
  dockVisible,
  onToggleHeader,
  onToggleDock,
}: {
  projects: Project[]
  currentProjectId: string
  active: ModuleKey
  collapsed: boolean
  width?: number
  onToggle: () => void
  onResize?: (w: number) => void
  onSelectProject: (id: string) => void
  onNavigate: (key: ModuleKey) => void
  onCreateSession: (kind: SessionKind) => void
  onProjectAction: (action: 'create' | 'rename' | 'delete', name?: string) => void
  assetsDirty?: boolean
  findingsDirty?: boolean
  headerVisible: boolean
  dockVisible: boolean
  onToggleHeader: () => void
  onToggleDock: () => void
}) {
  useLang()
  const draggingRef = useRef(false)

  function startDrag() {
    draggingRef.current = true
    document.body.style.cursor = 'col-resize'
    function onMove(e: MouseEvent) {
      if (!draggingRef.current) return
      onResize?.(e.clientX)
    }
    function onUp() {
      draggingRef.current = false
      document.body.style.cursor = ''
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  return (
    <nav className={cn('sidebar', collapsed && 'collapsed')} style={{ width: collapsed ? 60 : width }}>
      <div className="brand">
        <span className="brand-mark" aria-hidden>
          <LatticeLogo size={18} />
        </span>
        <span className="brand-text">Lattice AI</span>
        <button className="sidebar-toggle" onClick={onToggle} aria-label={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}>
          {collapsed ? '→' : '←'}
        </button>
      </div>
      <ProjectMenu
        projects={projects}
        currentProjectId={currentProjectId}
        collapsed={collapsed}
        onCreateSession={onCreateSession}
        onCreate={(name) => onProjectAction('create', name)}
        onRename={(name) => onProjectAction('rename', name)}
        onDelete={() => onProjectAction('delete')}
        onSwitch={onSelectProject}
      />
      <div className="nav">
        {MODULES.map((module) => (
          <button
            key={module.key}
            className={cn('nav-item', active === module.key && 'active')}
            onClick={() => onNavigate(module.key)}
            aria-current={active === module.key ? 'page' : undefined}
          >
            <span className="nav-icon" aria-hidden>
              {module.icon}
            </span>
            <span className="sidebar-label">{t(`module.${module.key}`)}</span>
            {module.key === 'assets' && assetsDirty && (
              <span className="nav-dot" data-testid="nav-dot-assets" aria-label={t('dot.assets')} />
            )}
            {module.key === 'findings' && findingsDirty && (
              <span className="nav-dot" data-testid="nav-dot-findings" aria-label={t('dot.findings')} />
            )}
          </button>
        ))}
      </div>
      <div className="layout-controls">
        <button type="button" onClick={onToggleHeader} aria-pressed={headerVisible}>
          <span aria-hidden>{headerVisible ? <EyeSlash size={16} weight="duotone" /> : <Eye size={16} weight="duotone" />}</span>
          <span>{headerVisible ? t('layout.hideHeader') : t('layout.showHeader')}</span>
        </button>
        {active !== 'run' && (
          <button type="button" onClick={onToggleDock} aria-pressed={dockVisible}>
            <span aria-hidden>{dockVisible ? <ChatCircle size={16} weight="duotone" /> : <ChatCircleDots size={16} weight="duotone" />}</span>
            <span>{dockVisible ? t('layout.hideDock') : t('layout.showDock')}</span>
          </button>
        )}
      </div>
      <div className="sidebar-resizer" role="separator" aria-orientation="vertical" onMouseDown={startDrag} title={t('sidebar.resize')} />
    </nav>
  )
}
