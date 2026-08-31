import { useEffect, useState, type ReactNode } from 'react'
import { Globe, Network, ShieldWarning, Crosshair, ArrowRight } from '@phosphor-icons/react'
import { getDashboard } from '../api'
import { Button } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { severityKey } from '../components/ui/SeverityBadge'
import { Skeleton } from '../components/ui/Skeleton'
import { t, useLang } from '../i18n'
import type { DashboardData, DashboardKpi } from '../types'

function Sparkline({ values }: { values: number[] }) {
  const max = Math.max(...values, 1)
  const w = 120
  const h = 32
  const pad = 2
  const step = (w - pad * 2) / Math.max(values.length - 1, 1)
  const points = values.map(
    (v, i) => `${(pad + i * step).toFixed(1)},${(h - pad - (v / max) * (h - pad * 2)).toFixed(1)}`,
  )
  return (
    <svg className="sparkline" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden>
      <polygon className="sparkline-area" points={`${pad},${h - pad} ${points.join(' ')} ${w - pad},${h - pad}`} />
      <polyline className="sparkline-line" points={points.join(' ')} />
    </svg>
  )
}

function timeLabel(value: string | undefined): string {
  return (value ?? '').replace('T', ' ').slice(0, 16)
}

function KpiCard({ kpi, label, icon, sub, loading }: { kpi: DashboardKpi; label: string; icon: ReactNode; sub?: string; loading: boolean }) {
  return (
    <div className="stat-card dash-kpi">
      <span className="stat-card-head">
        <span className="stat-icon" aria-hidden>
          {icon}
        </span>
        {sub && <span className="dash-kpi-sub">{sub}</span>}
      </span>
      <span className="stat-value">{loading ? '—' : kpi.total}</span>
      <span className="stat-label">{label}</span>
      <Sparkline values={kpi.spark} />
    </div>
  )
}

export default function DashboardPage({
  refreshKey,
  onNavigate,
}: {
  refreshKey: number
  /** 预留：当前固定项目级聚合，会话归属一致后再接线（P1 修复，勿传给 getDashboard） */
  sessionId?: string
  onNavigate: (key: 'findings' | 'run') => void
}) {
  useLang()
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    setLoading(true)
    // 空 session_id = 项目级聚合；会话 ID 会把 runs/assets 过滤成接近全 0
    getDashboard('')
      .then((result) => {
        if (alive) {
          setData(result)
          setLoading(false)
        }
      })
      .catch(() => {
        if (alive) {
          setData(null)
          setLoading(false)
        }
      })
    return () => {
      alive = false
    }
  }, [refreshKey])

  const kpis = data?.kpis
  const findingsKpi = kpis?.findings
  const criticalHigh =
    findingsKpi?.severity ? `${t('dash.kpi.criticalHigh')} ${findingsKpi.severity.critical + findingsKpi.severity.high}` : ''

  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-heading-main">
          <h2 className="page-heading-title">{t('dash.title')}</h2>
          <p className="page-heading-desc">{t('dash.desc')}</p>
        </div>
      </div>

      <div className="page-body">
        <div className="stat-grid" aria-busy={loading}>
          <KpiCard kpi={kpis?.assets ?? { total: 0, spark: [] }} label={t('dash.kpi.assets')} icon={<Network size={15} weight="bold" />} loading={loading} />
          <KpiCard kpi={kpis?.subdomains ?? { total: 0, spark: [] }} label={t('dash.kpi.subdomains')} icon={<Globe size={15} weight="bold" />} loading={loading} />
          <KpiCard kpi={kpis?.findings ?? { total: 0, spark: [] }} label={t('dash.kpi.findings')} icon={<ShieldWarning size={15} weight="bold" />} sub={criticalHigh} loading={loading} />
          <KpiCard kpi={kpis?.runs ?? { total: 0, spark: [] }} label={t('dash.kpi.runs')} icon={<Crosshair size={15} weight="bold" />} loading={loading} />
        </div>

        <div className="dash-grid">
          <section className="card dash-feed" aria-label={t('dash.feed.runs')}>
            <header className="dash-feed-head">
              <h3>{t('dash.feed.runs')}</h3>
              <Button size="sm" variant="ghost" icon={<ArrowRight size={13} weight="bold" />} onClick={() => onNavigate('run')}>
                {t('dash.viewAll')}
              </Button>
            </header>
            {loading ? (
              <div className="dash-feed-list">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="dash-feed-row">
                    <Skeleton className="skeleton" style={{ width: '45%' }} />
                    <Skeleton className="skeleton" style={{ width: 90 }} />
                  </div>
                ))}
              </div>
            ) : !data || data.recent_runs.length === 0 ? (
              <EmptyState title={t('dash.empty.runs')} icon={<Crosshair size={24} weight="duotone" />} />
            ) : (
              <ul className="dash-feed-list">
                {data.recent_runs.map((run) => (
                  <li key={run.id} className="dash-feed-row">
                    <span className="dash-feed-main">
                      <span className="dash-feed-title">{run.target || run.id}</span>
                      <span className="dash-feed-meta">{run.template_id}</span>
                    </span>
                    <span className="dash-feed-time">{timeLabel(run.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card dash-feed" aria-label={t('dash.feed.findings')}>
            <header className="dash-feed-head">
              <h3>{t('dash.feed.findings')}</h3>
              <Button size="sm" variant="ghost" icon={<ArrowRight size={13} weight="bold" />} onClick={() => onNavigate('findings')}>
                {t('dash.viewAll')}
              </Button>
            </header>
            {loading ? (
              <div className="dash-feed-list">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="dash-feed-row">
                    <Skeleton className="skeleton" style={{ width: '55%' }} />
                    <Skeleton className="skeleton" style={{ width: 70 }} />
                  </div>
                ))}
              </div>
            ) : !data || data.recent_findings.length === 0 ? (
              <EmptyState
                title={t('dash.empty.findings')}
                icon={<ShieldWarning size={24} weight="duotone" />}
                action={
                  <Button size="sm" variant="secondary" onClick={() => onNavigate('run')}>
                    {t('dash.goRun')}
                  </Button>
                }
              />
            ) : (
              <ul className="dash-feed-list">
                {data.recent_findings.map((finding) => (
                  <li key={finding.id} className="dash-feed-row">
                    <span className="dash-feed-main">
                      <span className="dash-feed-title">
                        <span className={`sev-dot sev-${severityKey(finding.severity)}`} aria-hidden />
                        {finding.title}
                      </span>
                      <span className="dash-feed-meta">{finding.target}</span>
                    </span>
                    <span className="dash-feed-time">{timeLabel(finding.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
