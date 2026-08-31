import { useState } from 'react'
import { Plus } from '@phosphor-icons/react'
import { createGroup, deleteGroup, listGroups, renameGroup, setGroupMembers, type AssetGroup } from '../api'
import { t, useLang } from '../i18n'
import { Button } from './ui/Button'
import { ConfirmDialog } from './ui/ConfirmDialog'
import { NameDialog } from './ui/NameDialog'
import { Tag } from './ui/Tag'

async function loadGroups(kind: 'tool' | 'skill'): Promise<AssetGroup[]> {
  const payload = await listGroups()
  return kind === 'tool' ? payload.tool_groups : payload.skill_groups
}

export function AssetGroups({
  kind,
  groups,
  assets,
  onGroupsChange,
  onApply,
}: {
  kind: 'tool' | 'skill'
  groups: AssetGroup[]
  assets: { name: string }[]
  onGroupsChange: (groups: AssetGroup[]) => void
  onApply: (items: string[]) => void
}) {
  const [creating, setCreating] = useState(false)
  const [renaming, setRenaming] = useState<AssetGroup | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState<AssetGroup | null>(null)
  const [editingMembers, setEditingMembers] = useState<AssetGroup | null>(null)
  const [draftMembers, setDraftMembers] = useState<string[]>([])
  useLang()

  const kindName = kind === 'tool' ? t('agrp.tool') : t('agrp.skill')
  const withKind = (template: string) => template.split('{name}').join(kindName)
  const assetNames = assets.map((a) => a.name)

  async function refresh(groupsOverride?: AssetGroup[]) {
    onGroupsChange(groupsOverride ?? (await loadGroups(kind)))
  }

  async function handleCreate(name: string) {
    await createGroup(kind, name)
    setCreating(false)
    await refresh()
  }

  async function handleRename(name: string) {
    if (!renaming) return
    await renameGroup(kind, renaming.id, name)
    setRenaming(null)
    await refresh()
  }

  async function handleDelete() {
    if (!confirmingDelete) return
    await deleteGroup(kind, confirmingDelete.id)
    setConfirmingDelete(null)
    await refresh()
  }

  function openMembers(group: AssetGroup) {
    setEditingMembers(group)
    setDraftMembers(group.members)
  }

  async function saveMembers() {
    if (!editingMembers) return
    await setGroupMembers(kind, editingMembers.id, draftMembers)
    setEditingMembers(null)
    await refresh()
  }

  return (
    <div className="asset-groups">
      <div className="section-toolbar">
        <Tag tone="primary">{withKind(t('agrp.tag'))}</Tag>
        <Button size="sm" variant="ghost" icon={<Plus size={14} weight="bold" />} onClick={() => setCreating(true)}>
          {withKind(t('agrp.create'))}
        </Button>
      </div>

      {groups.length === 0 ? (
        <p className="muted asset-groups-empty">{withKind(t('agrp.empty'))}</p>
      ) : (
        <div className="group-grid">
          {groups.map((group) => (
            <div key={group.id} className="card group-card">
              <div className="group-card-head">
                <div className="group-card-title">{group.name}</div>
                <div className="card-actions">
                  <Button size="sm" variant="ghost" onClick={() => setRenaming(group)}>
                    {t('agrp.rename')}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => openMembers(group)}>
                    {t('agrp.members')}
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => setConfirmingDelete(group)}>
                    {t('agrp.delete')}
                  </Button>
                </div>
              </div>
              <div className="group-members">
                {group.members.length === 0 ? (
                  <span className="muted group-members-empty">{t('agrp.noMembers')}</span>
                ) : (
                  group.members.map((member) => <Tag key={member}>{member}</Tag>)
                )}
              </div>
              <div className="group-card-actions">
                <Button size="sm" variant="secondary" onClick={() => onApply(group.members)}>
                  {t('agrp.useInWorkflow')}
                </Button>
              </div>

              {editingMembers?.id === group.id && (
                <div className="group-member-editor">
                  <div className="group-member-editor-title">
                    {t('agrp.memberEditor')}
                    <div className="card-actions">
                      <Button size="sm" onClick={saveMembers}>
                        {t('common.save')}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditingMembers(null)}>
                        {t('common.cancel')}
                      </Button>
                    </div>
                  </div>
                  {assetNames.length === 0 ? (
                    <p className="muted">{withKind(t('agrp.noneAvailable'))}</p>
                  ) : (
                    <div className="group-member-list">
                      {assetNames.map((name) => (
                        <label key={name} className="check-label">
                          <input
                            type="checkbox"
                            checked={draftMembers.includes(name)}
                            onChange={(event) =>
                              setDraftMembers((prev) =>
                                event.target.checked ? [...prev, name] : prev.filter((n) => n !== name),
                              )
                            }
                          />
                          {name}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <NameDialog open={creating} title={withKind(t('agrp.create'))} confirmLabel={t('agrp.create.confirm')} onConfirm={handleCreate} onCancel={() => setCreating(false)} />
      <NameDialog open={!!renaming} title={withKind(t('agrp.rename.title'))} initialValue={renaming?.name ?? ''} confirmLabel={t('common.save')} onConfirm={handleRename} onCancel={() => setRenaming(null)} />
      <ConfirmDialog
        open={!!confirmingDelete}
        title={withKind(t('agrp.delete.title'))}
        description={t('agrp.delete.desc').replace('{name}', confirmingDelete?.name ?? '')}
        confirmLabel={t('agrp.delete')}
        danger
        onConfirm={handleDelete}
        onCancel={() => setConfirmingDelete(null)}
      />
    </div>
  )
}
