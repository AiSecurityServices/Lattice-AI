import { useEffect, useState } from 'react'
import { Trash as TrashIcon } from '@phosphor-icons/react'
import { emptyTrash, listTrash, purgeTrash, restoreTrash, type TrashItem } from '../api'
import { t, useLang } from '../i18n'
import { Button } from '../components/ui/Button'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'
import { EmptyState } from '../components/ui/EmptyState'
import { formatRelative } from '../lib/format'

const kindLabelKey: Record<TrashItem['kind'], string> = {
  templates: 'trash.kind.templates',
  tools: 'trash.kind.tools',
  skills: 'trash.kind.skills',
  projects: 'module.project',
  conversations: 'panel.sessions',
}

export default function TrashPage({ refreshKey, onRestored }: { refreshKey: number; onRestored?: () => void }) {
  useLang()
  const [items, setItems] = useState<TrashItem[]>([])
  const [error, setError] = useState('')
  const [purgeItem, setPurgeItem] = useState<TrashItem | null>(null)
  const [emptyTarget, setEmptyTarget] = useState<TrashItem['kind'] | 'all' | null>(null)

  async function load() {
    setError('')
    try {
      setItems((await listTrash()).items)
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    load()
  }, [refreshKey])

  async function restore(item: TrashItem) {
    setError('')
    try {
      await restoreTrash(item.kind, item.name)
      await load()
      onRestored?.()
    } catch (e) {
      setError(String(e))
    }
  }

  async function purgeConfirmed() {
    if (!purgeItem) return
    try {
      await purgeTrash(purgeItem.kind, purgeItem.name)
      setPurgeItem(null)
      await load()
    } catch (caught) {
      setError(String(caught))
    }
  }

  async function emptyConfirmed() {
    if (!emptyTarget) return
    try {
      await emptyTrash(emptyTarget === 'all' ? undefined : emptyTarget)
      setEmptyTarget(null)
      await load()
    } catch (caught) {
      setError(String(caught))
    }
  }

  return (
    <div className="page">
      <div className="page-heading">
        <h2 className="page-heading-title">{t('module.trash')}</h2>
        {items.length > 0 && (
          <Button size="sm" variant="danger" onClick={() => setEmptyTarget('all')}>
            {t('trash.emptyAll')}
          </Button>
        )}
      </div>
      {error && <div className="text-danger">{error}</div>}
      {items.length === 0 ? (
        <EmptyState title={t('trash.empty.title')} description={t('trash.empty.desc')} icon={<TrashIcon size={22} weight="duotone" />} />
      ) : (
        <div className="asset-group">
          <div className="template-grid">
            {items.map((item) => {
              const label = item.display_name || item.name
              return (
                <div key={`${item.kind}:${item.name}`} className="card template-card">
                  <div className="template-card-title">{label}</div>
                  <div className="template-card-meta">
                    {t(kindLabelKey[item.kind])} · {t('trash.deletedAt')} {formatRelative(item.deleted_at)}
                  </div>
                  {item.display_name && item.display_name !== item.name && (
                    <div className="template-card-meta">
                      <span className="tpl-card-id">{item.name}</span>
                    </div>
                  )}
                  <div className="template-card-actions">
                    <Button size="sm" onClick={() => restore(item)}>
                      {t('trash.restore')}
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => setPurgeItem(item)}>
                      {t('trash.purge')}
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
      <ConfirmDialog
        open={!!purgeItem}
        title={t('trash.purge')}
        description={t('trash.purgeConfirm').replace('{name}', purgeItem?.name ?? '')}
        confirmLabel={t('trash.purge')}
        danger
        onConfirm={() => void purgeConfirmed()}
        onCancel={() => setPurgeItem(null)}
      />
      <ConfirmDialog
        open={!!emptyTarget}
        title={t('trash.emptyAll')}
        description={t('trash.emptyConfirm')}
        confirmLabel={t('trash.clear')}
        danger
        onConfirm={() => void emptyConfirmed()}
        onCancel={() => setEmptyTarget(null)}
      />
    </div>
  )
}
