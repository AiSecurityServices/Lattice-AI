import { useEffect, useMemo, useState } from 'react'
import { ArrowClockwise, CaretRight, ListMagnifyingGlass, MagnifyingGlass } from '@phosphor-icons/react'
import { listLogs } from '../api'
import { t, useLang } from '../i18n'
import { Button } from '../components/ui/Button'
import { formatTime } from '../lib/format'
import { describeLog, logTypeLabel } from '../lib/logs'
import type { LogLine } from '../types'

export default function LogsPage({ refreshKey }: { refreshKey: number }) {
  useLang()
  const [logs, setLogs] = useState<LogLine[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('')

  async function load() {
    setLoading(true)
    setLogs((await listLogs()).logs)
    setLoading(false)
  }

  useEffect(() => {
    load()
  }, [refreshKey])

  const types = useMemo(() => [...new Set(logs.map((log) => log.type ?? 'event'))], [logs])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return logs.filter((log) => {
      if (typeFilter && (log.type ?? 'event') !== typeFilter) return false
      if (!q) return true
      const haystack = `${log.type ?? ''} ${describeLog(log)} ${JSON.stringify(log.data ?? {})}`.toLowerCase()
      return haystack.includes(q)
    })
  }, [logs, query, typeFilter])

  return (
    <div className="page">
      <div className="page-heading">
        <h2 className="page-heading-title">{t('module.logs')}</h2>
        <div className="page-heading-actions">
          <span className="muted page-heading-count">{t('logsp.count').replace('{count}', String(filtered.length))}</span>
          <label className="search-input">
            <MagnifyingGlass size={14} weight="bold" />
            <input className="input" placeholder={t('logsp.searchPlaceholder')} value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <select className="select" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} aria-label={t('logsp.typeFilterAria')}>
            <option value="">{t('logsp.allTypes')}</option>
            {types.map((type) => (
              <option key={type} value={type}>
                {logTypeLabel(type)}
              </option>
            ))}
          </select>
          <Button size="sm" variant="ghost" icon={<ArrowClockwise size={15} weight="bold" />} onClick={load}>
            {t('logsp.refresh')}
          </Button>
        </div>
      </div>

      <div className="page-body">
        {loading ? (
          <div className="log-viewer">
            {[0, 1, 2].map((i) => (
              <div key={i} className="log-row">
                <div className="skeleton" style={{ width: '40%' }} />
              </div>
            ))}
          </div>
        ) : logs.length === 0 ? (
          <div className="empty">
            <div className="empty-icon" aria-hidden>
              <ListMagnifyingGlass size={22} weight="duotone" />
            </div>
            <div className="empty-title">{t('logsp.emptyTitle')}</div>
            <div className="empty-desc">{t('logsp.emptyDesc')}</div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="empty">
            <div className="empty-icon" aria-hidden>
              <ListMagnifyingGlass size={22} weight="duotone" />
            </div>
            <div className="empty-title">{t('logsp.noMatchTitle')}</div>
            <div className="empty-desc">{t('logsp.noMatchDesc')}</div>
          </div>
        ) : (
          <div className="log-viewer">
            {filtered.map((log, index) => (
              <details key={`${log.run_id}-${log.seq ?? index}`} className="log-row">
                <summary className="log-line">
                  <CaretRight size={12} weight="bold" className="log-chevron" aria-hidden />
                  <span className="log-time mono-area">{formatTime(log.created_at ?? log.run_id)}</span>
                  <span className="log-type">{logTypeLabel(log.type)}</span>
                  <span className="log-summary">{describeLog(log)}</span>
                </summary>
                <pre className="log-data">{JSON.stringify(log.data, null, 2)}</pre>
              </details>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
