import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Cpu,
  Cube,
  GlobeSimple,
  HardDrive,
  MagnifyingGlass,
  Network,
  Path,
  Plugs,
  ShareNetwork,
} from '@phosphor-icons/react'
import { getAssetGraph, listAssets } from '../api'
import { AssetGraph } from '../components/AssetGraph'
import { Button } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { SegmentedControl } from '../components/ui/SegmentedControl'
import { Skeleton } from '../components/ui/Skeleton'
import { Tag } from '../components/ui/Tag'
import { t, useLang } from '../i18n'
import type { Asset, AssetGraph as AssetGraphData, AssetKind } from '../types'

function kindMeta(): Record<AssetKind, { label: string; icon: ReactNode }> {
  return {
    domain: { label: t('assets.kind.domain'), icon: <GlobeSimple size={15} weight="bold" /> },
    subdomain: { label: t('assets.kind.subdomain'), icon: <ShareNetwork size={15} weight="bold" /> },
    ip: { label: t('assets.kind.ip'), icon: <HardDrive size={15} weight="bold" /> },
    port: { label: t('assets.kind.port'), icon: <Plugs size={15} weight="bold" /> },
    service: { label: t('assets.kind.service'), icon: <Cube size={15} weight="bold" /> },
    technology: { label: t('assets.kind.technology'), icon: <Cpu size={15} weight="bold" /> },
    endpoint: { label: t('assets.kind.endpoint'), icon: <Path size={15} weight="bold" /> },
  }
}

const KIND_ORDER: AssetKind[] = ['domain', 'subdomain', 'ip', 'port', 'service', 'technology', 'endpoint']

function formatTime(iso?: string): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export default function AssetsPage({
  refreshKey,
  onNavigate,
  sessionId,
  sessionName,
}: {
  refreshKey: number
  onNavigate: (key: 'run' | 'findings') => void
  sessionId: string
  sessionName?: string
}) {
  const [assets, setAssets] = useState<Asset[]>([])
  const [graph, setGraph] = useState<AssetGraphData>({ nodes: [], edges: [] })
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState<'' | AssetKind>('')
  const [loading, setLoading] = useState(true)
  // Dashboard KPIs aggregate across the project while this page used to filter
  // to the active session only — numbers contradicted each other with no hint
  // why. Project scope is the default and the toggle states itself.
  const [scope, setScope] = useState<'project' | 'session'>('project')
  useLang()
  const KIND_META = kindMeta()

  useEffect(() => {
    if (scope === 'session' && !sessionId) {
      setAssets([])
      setGraph({ nodes: [], edges: [] })
      setLoading(false)
      return
    }
    setLoading(true)
    const sid = scope === 'session' ? sessionId : ''
    Promise.all([listAssets(sid ? { session_id: sid } : {}), getAssetGraph('', 200, sid || undefined)])
      .then(([assetResult, graphData]) => {
        setAssets(assetResult.assets)
        setGraph(graphData)
      })
      .finally(() => setLoading(false))
  }, [refreshKey, sessionId, scope])

  const counts = useMemo(() => {
    const result = {} as Record<AssetKind, number>
    for (const kindKey of KIND_ORDER) result[kindKey] = 0
    for (const asset of assets) {
      if (asset.kind in result) result[asset.kind] += 1
    }
    return result
  }, [assets])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return assets.filter((asset) => {
      if (kind !== '' && asset.kind !== kind) return false
      if (!q) return true
      return (
        asset.value.toLowerCase().includes(q) ||
        asset.kind.includes(q) ||
        (asset.source_tool ?? '').toLowerCase().includes(q)
      )
    })
  }, [assets, kind, query])

  function statCard(value: AssetKind | '', label: string, icon: ReactNode, tone?: 'danger' | 'warning' | 'success') {
    const count = value === '' ? assets.length : counts[value]
    return (
      <button
        key={value || 'all'}
        type="button"
        className={`stat-card ${tone ?? ''} ${kind === value ? 'active' : ''}`}
        onClick={() => setKind(value as '' | AssetKind)}
        aria-pressed={kind === value}
      >
        <span className="stat-card-head">
          <span className="stat-icon" aria-hidden>
            {icon}
          </span>
        </span>
        <span className="stat-value">{loading ? '—' : count}</span>
        <span className="stat-label">{label}</span>
      </button>
    )
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-heading-main">
          <h2 className="page-heading-title">{t('module.assets')}</h2>
          <p className="page-heading-desc">{t('assets.desc')}</p>
        </div>
        <div className="page-heading-actions">
          <SegmentedControl
            options={[
              { value: 'project', label: t('assets.scope.project') },
              {
                value: 'session',
                label: t('assets.scope.session').replace(
                  '{name}',
                  sessionName ? `${t('assets.scope.sessionSep')}${sessionName}` : '',
                ),
              },
            ]}
            value={scope}
            onChange={(value) => setScope(value as 'project' | 'session')}
            ariaLabel={t('assets.scope.aria')}
          />
          <select className="select" value={kind} onChange={(e) => setKind(e.target.value as '' | AssetKind)} aria-label={t('assets.kind.aria')}>
            <option value="">{t('assets.kind.all')}</option>
            {KIND_ORDER.map((kindKey) => (
              <option key={kindKey} value={kindKey}>
                {KIND_META[kindKey].label}
              </option>
            ))}
          </select>
          <label className="search-input">
            <MagnifyingGlass size={14} weight="bold" />
            <input className="input" placeholder={t('assets.search.placeholder')} value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <span className="muted page-heading-count">
            {filtered.length} / {assets.length}
          </span>
        </div>
      </div>

      <div className="page-body">
        {loading ? (
          <>
            <div className="stat-grid" aria-busy="true" aria-label={t('assets.stats.loading.aria')}>
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="card" style={{ gap: 10, display: 'flex', flexDirection: 'column' }}>
                  <Skeleton className="skeleton" style={{ width: 28, height: 28 }} />
                  <Skeleton className="skeleton" style={{ width: 48, height: 22 }} />
                  <Skeleton className="skeleton" style={{ width: 72 }} />
                </div>
              ))}
            </div>
            <div className="card graph-card">
              <div className="graph-card-head">
                <span className="stat-icon" aria-hidden>
                  <Network size={16} weight="bold" />
                </span>
                <span className="graph-card-title">{t('assets.graph.title')}</span>
              </div>
              <div className="asset-graph-empty">{t('assets.graph.loading')}</div>
            </div>
            <div className="table-wrap">
              <table className="data-table" aria-label={t('assets.list')}>
                <tbody>
                  {[0, 1, 2, 3, 4].map((i) => (
                    <tr key={i}>
                      <td>
                        <Skeleton className="skeleton" style={{ width: 80 }} />
                      </td>
                      <td>
                        <Skeleton className="skeleton" style={{ width: '70%' }} />
                      </td>
                      <td>
                        <Skeleton className="skeleton" style={{ width: 60 }} />
                      </td>
                      <td>
                        <Skeleton className="skeleton" style={{ width: 40 }} />
                      </td>
                      <td>
                        <Skeleton className="skeleton" style={{ width: 90 }} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : assets.length === 0 ? (
          <EmptyState
            title={t('assets.empty.title')}
            description={t('assets.empty.desc')}
            icon={<Network size={24} weight="duotone" />}
            action={
              <Button variant="primary" onClick={() => onNavigate('run')}>
                {t('assets.gotoRun')}
              </Button>
            }
          />
        ) : (
          <>
            <div className="stat-grid">
              {statCard('', t('assets.stats.total'), <Network size={16} weight="bold" />)}
              {KIND_ORDER.map((kindKey) =>
                statCard(kindKey, KIND_META[kindKey].label, KIND_META[kindKey].icon, kindKey === 'endpoint' ? 'warning' : undefined),
              )}
            </div>

            <div className="card graph-card">
              <div className="graph-card-head">
                <span className="stat-icon" aria-hidden>
                  <Network size={16} weight="bold" />
                </span>
                <span className="graph-card-title">{t('assets.graph.title')}</span>
                <span className="graph-card-meta">
                  {t('assets.graph.meta')
                    .replace('{nodes}', String(graph.nodes.length))
                    .replace('{edges}', String(graph.edges.length))}
                </span>
              </div>
              <AssetGraph graph={graph} />
            </div>

            <div className="asset-group">
              <div className="section-toolbar">
                <h4 className="section-label">{t('assets.list')}</h4>
                {filtered.length > 0 && (
                  <span className="muted">
                    {t('assets.count').replace('{n}', String(filtered.length))}
                    {query.trim() && t('assets.search.query').replace('{q}', query.trim())}
                  </span>
                )}
              </div>

              {filtered.length === 0 ? (
                <EmptyState
                  title={t('assets.emptyFiltered.title')}
                  description={t('assets.emptyFiltered.desc')}
                  icon={<MagnifyingGlass size={24} weight="duotone" />}
                  action={
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setQuery('')
                        setKind('')
                      }}
                    >
                      {t('assets.clearFilters')}
                    </Button>
                  }
                />
              ) : (
                <div className="table-wrap">
                  <table className="data-table" aria-label={t('assets.list')}>
                    <colgroup>
                      <col style={{ width: '110px' }} />
                      <col />
                      <col style={{ width: '120px' }} />
                      <col style={{ width: '80px' }} />
                      <col style={{ width: '140px' }} />
                    </colgroup>
                    <thead>
                      <tr>
                        <th>{t('assets.col.kind')}</th>
                        <th>{t('assets.col.asset')}</th>
                        <th>{t('assets.col.sourceTool')}</th>
                        <th>{t('assets.col.evidence')}</th>
                        <th>{t('assets.col.lastSeen')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((asset) => (
                        <tr key={asset.id}>
                          <td>
                            <span className="kind-badge">
                              <span aria-hidden>{KIND_META[asset.kind]?.icon ?? <Cube size={15} weight="bold" />}</span>
                              <span className="kind-name">{KIND_META[asset.kind]?.label ?? asset.kind}</span>
                            </span>
                          </td>
                          <td>
                            <span className="cell-main" title={asset.value}>
                              {asset.value}
                            </span>
                          </td>
                          <td>
                            {asset.source_tool ? (
                              <Tag>{asset.source_tool}</Tag>
                            ) : (
                              <span className="cell-muted">—</span>
                            )}
                          </td>
                          <td>
                            <span className="cell-muted">{(asset.evidence_ids ?? []).length}</span>
                          </td>
                          <td>
                            <span className="cell-muted">{formatTime(asset.last_seen)}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
