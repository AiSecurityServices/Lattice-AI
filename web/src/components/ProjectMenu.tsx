import { useEffect, useRef, useState } from 'react'
import { Copy, DotsThree, PencilSimple, Plus, Trash } from '@phosphor-icons/react'
import type { Project, SessionKind } from '../types'
import { t, useLang } from '../i18n'
import { Button } from './ui/Button'
import { ConfirmDialog } from './ui/ConfirmDialog'

export function ProjectMenu({
  projects,
  currentProjectId,
  collapsed = false,
  onCreateSession,
  onCreate,
  onRename,
  onDelete,
  onSwitch,
}: {
  projects: Project[]
  currentProjectId: string
  collapsed?: boolean
  onCreateSession: (kind: SessionKind) => void
  onCreate: (name: string) => void
  onRename: (name: string) => void
  onDelete: () => void
  onSwitch: (id: string) => void
}) {
  useLang()
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [nameDialog, setNameDialog] = useState<{ type: 'create' | 'rename'; value: string } | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const currentProject = projects.find((project) => project.id === currentProjectId)

  useEffect(() => {
    if (!menuOpen) return
    function onPointerDown(event: MouseEvent) {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen])

  function openCreate() {
    setMenuOpen(false)
    setNameDialog({ type: 'create', value: '' })
  }

  function openRename() {
    setMenuOpen(false)
    setNameDialog({ type: 'rename', value: currentProject?.name ?? '' })
  }

  function openDelete() {
    setMenuOpen(false)
    setConfirmingDelete(true)
  }

  function switchTo(id: string) {
    setMenuOpen(false)
    onSwitch(id)
  }

  return (
    <>
      <div className="project-menu">
        {collapsed ? (
          <button
            className="project-chip"
            aria-label={t('pmenu.switchProject')}
            onClick={() => setMenuOpen((value) => !value)}
          >
            <span className="project-chip-avatar">{currentProject?.name?.[0]?.toUpperCase() ?? '?'}</span>
          </button>
        ) : (
          <select
            className="select"
            aria-label={t('pmenu.currentProject')}
            value={currentProjectId}
            onChange={(event) => onSwitch(event.target.value)}
          >
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        )}

        <div className="project-menu-actions" ref={menuRef}>
          {!collapsed && (
            <Button
              size="sm"
              variant="ghost"
              aria-label={t('pmenu.createProject')}
              icon={<Plus size={16} weight="bold" />}
              onClick={openCreate}
            />
          )}
          <Button
            size="sm"
            variant="ghost"
            aria-label={t('pmenu.menu')}
            icon={<DotsThree size={18} weight="bold" />}
            onClick={() => setMenuOpen((value) => !value)}
          />
          {menuOpen && (
            <div className="popover-menu" role="menu">
              {collapsed && (
                <>
                  {projects.map((project) => (
                    <button
                      key={project.id}
                      role="menuitem"
                      className={currentProjectId === project.id ? 'active' : undefined}
                      onClick={() => switchTo(project.id)}
                    >
                      {project.name}
                    </button>
                  ))}
                  <div className="popover-sep" />
                </>
              )}
              <div className="popover-sep" />
              <button role="menuitem" onClick={() => { setMenuOpen(false); onCreateSession('task') }}>
                <Plus size={15} weight="bold" />
                {t('pmenu.newSession')}
              </button>
              <div className="popover-sep" />
              <button role="menuitem" onClick={openCreate}>
                <Copy size={15} weight="bold" />
                {t('pmenu.createProject')}
              </button>
              <button role="menuitem" onClick={openRename}>
                <PencilSimple size={15} weight="bold" />
                {t('pmenu.rename')}
              </button>
              <button role="menuitem" className="danger" onClick={openDelete}>
                <Trash size={15} weight="bold" />
                {t('pmenu.delete')}
              </button>
            </div>
          )}
        </div>
      </div>

      {nameDialog && (
        <div className="dialog-backdrop" onMouseDown={() => setNameDialog(null)}>
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-label={nameDialog.type === 'create' ? t('pmenu.createProject') : t('pmenu.renameProject')}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <h3>{nameDialog.type === 'create' ? t('pmenu.createProject') : t('pmenu.renameProject')}</h3>
            <label className="field">
              <span>{t('pmenu.nameLabel')}</span>
              <input
                className="input"
                autoFocus
                value={nameDialog.value}
                onChange={(event) => setNameDialog({ ...nameDialog, value: event.target.value })}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && nameDialog.value.trim()) {
                    const name = nameDialog.value.trim()
                    setNameDialog(null)
                    if (nameDialog.type === 'create') onCreate(name)
                    else onRename(name)
                  }
                  if (event.key === 'Escape') setNameDialog(null)
                }}
              />
            </label>
            <div className="dialog-actions">
              <Button onClick={() => setNameDialog(null)}>{t('common.cancel')}</Button>
              <Button
                variant="primary"
                disabled={!nameDialog.value.trim()}
                onClick={() => {
                  const name = nameDialog.value.trim()
                  setNameDialog(null)
                  if (nameDialog.type === 'create') onCreate(name)
                  else onRename(name)
                }}
              >
                {t('cd.confirm')}
              </Button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirmingDelete}
        title={t('pmenu.deleteConfirmTitle')}
        description={t('pmenu.deleteConfirmDesc')}
        confirmLabel={t('pmenu.confirmDelete')}
        danger
        onConfirm={() => {
          setConfirmingDelete(false)
          onDelete()
        }}
        onCancel={() => setConfirmingDelete(false)}
      />
    </>
  )
}
