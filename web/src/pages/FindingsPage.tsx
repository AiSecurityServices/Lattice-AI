import { useEffect, useMemo, useState } from 'react'
import { LinkSimple, MagnifyingGlass, ShieldWarning } from '@phosphor-icons/react'
import { listAssets, listEvidence, listFindings, updateFindingStatus } from '../api'
import { Button } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { GroundingBadge } from '../components/ui/GroundingBadge'
import { SegmentedControl } from '../components/ui/SegmentedControl'
import { SeverityBadge, severityKey } from '../components/ui/SeverityBadge'
import { Skeleton } from '../components/ui/Skeleton'
import { Tag } from '../components/ui/Tag'
import { t, useLang } from '../i18n'
import type { Evidence, Finding } from '../types'

type SeverityTone = 'danger' | 'warning' | 'success' | 'neutral'
type FindingStatus = 'confirmed' | 'pending' | 'false_positive' | 'needs_review'

const STATUS_CLASS: Record<FindingStatus, string> = {
  pending: 'status-warning',
  confirmed: 'status-success',
  false_positive: '',
  needs_review: 'status-warning',
}

function statusOptions(): Array<{ value: FindingStatus; label: string }> {
  return [
    { value: 'pending', label: t('find.status.pending') },
    { value: 'confirmed', label: t('find.status.confirmed') },
    { value: 'false_positive', label: t('find.status.falsePositive') },
    { value: 'needs_review', label: t('find.status.needsReview') },
  ]
}

function severityClass(value: string): string {
  return `sev-${severityKey(value)}`
}

function shortEvidenceId(id: string): string {
  return id.length > 24 ? `${id.slice(0, 10)}…${id.slice(-6)}` : id
}

export default function FindingsPage({
  refreshKey,
  onNavigate,
  sessionId,
  sessionName,
}: {
  refreshKey: number
  onNavigate: (key: 'assets' | 'run') => void
  sessionId: string
  sessionName?: string
}) {
  const [findings, setFindings] = useState<Finding[]>([])
  const [assetCounts, setAssetCounts] = useState<Record<string, number>>({})
  const [evidenceById, setEvidenceById] = useState<Record<string, Evidence>>({})
  const [severity, setSeverity] = useState('all')
  const [status, setStatus] = useState('all')
  const [grounding, setGrounding] = useState('all')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  useLang()

  useEffect(() => {
    if (!sessionId) {
      setFindings([])
      setLoading(false)
      return
    }
    setLoading(true)
    listFindings(sessionId)
      .then((result) => {
        setFindings(result.findings)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [refreshKey, sessionId])

  useEffect(() => {
    if (!sessionId) {
      setAssetCounts({})
      setEvidenceById({})
      return
    }
    listAssets({ session_id: sessionId }).then(({ assets }) => {
      const counts: Record<string, number> = {}
      for (const asset of assets) {
        for (const evidenceId of asset.evidence_ids ?? []) {
          counts[evidenceId] = (counts[evidenceId] ?? 0) + 1
        }
      }
      setAssetCounts(counts)
    })
    listEvidence(sessionId).then(({ evidence }) => {
      setEvidenceById(Object.fromEntries(evidence.map((item) => [item.id, item])))
    })
  }, [refreshKey, sessionId])

  async function changeStatus(finding: Finding, status: FindingStatus) {
    await updateFindingStatus(finding.id, status)
    setFindings((prev) => prev.map((item) => (item.id === finding.id ? { ...item, status } : item)))
  }

  const severityCounts = useMemo(() => {
    const counts: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0, info: 0 }
    for (const finding of findings) {
      const key = counts[finding.severity] !== undefined ? finding.severity : 'info'
      counts[key] += 1
    }
    return counts
  }, [findings])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return findings.filter((finding) => {
      if (severity !== 'all' && finding.severity !== severity) return false
      if (status !== 'all' && finding.status !== status) return false
      if (grounding !== 'all' && finding.grounding?.status !== grounding) return false
      if (!q) return true
      return (
        finding.title.toLowerCase().includes(q) ||
        (finding.target ?? '').toLowerCase().includes(q) ||
        (finding.cwe ?? '').toLowerCase().includes(q) ||
        (finding.summary ?? '').toLowerCase().includes(q)
      )
    })
  }, [findings, severity, status, grounding, query])

  function severityStat(value: string, label: string, tone: SeverityTone | '') {
    const count = value === 'all' ? findings.length : severityCounts[value]
    return (
      <button
        key={value}
        type="button"
        className={`stat-card ${tone ? `tone-${tone}` : ''} ${severity === value ? 'active' : ''}`}
        onClick={() => setSeverity(value)}
        aria-pressed={severity === value}
      >
        <span className="stat-card-head">
          <span className="stat-icon" aria-hidden>
            <ShieldWarning size={15} weight="bold" />
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
          <h2 className="page-heading-title">{t('module.findings')}</h2>
          <p className="page-heading-desc">{t('find.desc')}</p>
        </div>
        <div className="page-heading-actions">
          <span className="muted">{t('find.session').replace('{name}', sessionName || t('find.session.project'))}</span>
          <Button size="sm" variant="secondary" onClick={() => onNavigate('assets')}>
            {t('find.viewAssets')}
          </Button>
          <label className="search-input">
            <MagnifyingGlass size={14} weight="bold" />
            <input className="input" placeholder={t('find.search.placeholder')} value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <select className="select" value={severity} onChange={(event) => setSeverity(event.target.value)} aria-label={t('find.severity.aria')}>
            <option value="all">{t('find.severity.all')}</option>
            <option value="critical">{t('find.severity.critical')}</option>
            <option value="high">{t('find.severity.high')}</option>
            <option value="medium">{t('find.severity.medium')}</option>
            <option value="low">{t('find.severity.low')}</option>
            <option value="info">{t('find.severity.info')}</option>
          </select>
          <select className="select" value={grounding} onChange={(event) => setGrounding(event.target.value)} aria-label={t('gnd.filter.aria')}>
            <option value="all">{t('gnd.filter.all')}</option>
            <option value="verified">{t('gnd.status.verified')}</option>
            <option value="unverified">{t('gnd.status.unverified')}</option>
            <option value="missing_evidence">{t('gnd.status.missing_evidence')}</option>
          </select>
          <select className="select" value={status} onChange={(event) => setStatus(event.target.value)} aria-label={t('find.status.aria')}>
            <option value="all">{t('find.status.all')}</option>
            <option value="pending">{t('find.status.pending')}</option>
            <option value="confirmed">{t('find.status.confirmed')}</option>
            <option value="resolved">{t('find.status.resolved')}</option>
            <option value="false_positive">{t('find.status.falsePositive')}</option>
            <option value="needs_review">{t('find.status.needsReview')}</option>
          </select>
        </div>
      </div>

      <div className="page-body">
        {loading ? (
          <>
            <div className="stat-grid" aria-busy="true" aria-label={t('find.stats.loading.aria')}>
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="card" style={{ gap: 10, display: 'flex', flexDirection: 'column' }}>
                  <Skeleton className="skeleton" style={{ width: 28, height: 28 }} />
                  <Skeleton className="skeleton" style={{ width: 40, height: 22 }} />
                  <Skeleton className="skeleton" style={{ width: 64 }} />
                </div>
              ))}
            </div>
            <div className="finding-grid">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="card finding-card">
                  <div className="skeleton" style={{ width: 180, height: 16 }} />
                  <div className="skeleton" style={{ width: 240 }} />
                  <div className="skeleton" />
                  <div className="skeleton" style={{ width: '80%' }} />
                </div>
              ))}
            </div>
          </>
        ) : findings.length === 0 ? (
          <EmptyState
            title={t('find.empty.title')}
            description={t('find.empty.desc')}
            icon={<ShieldWarning size={24} weight="duotone" />}
            action={
              <Button variant="primary" onClick={() => onNavigate('run')}>
                {t('dash.goRun')}
              </Button>
            }
          />
        ) : (
          <>
            <div className="stat-grid stat-grid--six">
              {severityStat('all', t('find.stats.total'), '')}
              {severityStat('critical', t('sev.critical'), 'danger')}
              {severityStat('high', t('sev.high'), 'danger')}
              {severityStat('medium', t('sev.medium'), 'warning')}
              {severityStat('low', t('sev.low'), 'success')}
              {severityStat('info', t('sev.info'), '')}
            </div>

            {filtered.length === 0 ? (
              <EmptyState
                title={t('find.emptyFiltered.title')}
                description={t('find.emptyFiltered.desc')}
                icon={<MagnifyingGlass size={24} weight="duotone" />}
                action={
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setQuery('')
                      setSeverity('all')
                      setStatus('all')
                      setGrounding('all')
                    }}
                  >
                    {t('assets.clearFilters')}
                  </Button>
                }
              />
            ) : (
              <>
                <p className="muted" style={{ marginTop: 0, marginBottom: 12 }}>
                  {t('find.count').replace('{n}', String(filtered.length))}
                </p>
                <div className="finding-grid">
                  {filtered.map((finding) => {
                    const evidenceIds = finding.evidence_ids ?? []
                    const assetCount = evidenceIds.reduce((n, id) => n + (assetCounts[id] ?? 0), 0)
                    return (
                      <article key={finding.id} className={`card finding-card ${severityClass(finding.severity)}`}>
                        <div className="finding-head">
                          <span className="card-icon" aria-hidden>
                            <ShieldWarning size={15} weight="bold" />
                          </span>
                          <div className="finding-title">{finding.title}</div>
                          <SeverityBadge severity={finding.severity} />
                          <GroundingBadge status={finding.grounding?.status} />
                        </div>

                        {finding.target && <div className="finding-target">{finding.target}</div>}

                        <div className="finding-meta">
                          {finding.cwe && <Tag>{finding.cwe}</Tag>}
                          {finding.cvss && <Tag>CVSS {finding.cvss}</Tag>}
                          {finding.confidence && <Tag>{t('find.confidence').replace('{n}', String(finding.confidence))}</Tag>}
                        </div>

                        {finding.summary && <p className="finding-summary">{finding.summary}</p>}

                        {(finding.impact || finding.remediation) && (
                          <details className="finding-details">
                            <summary>{t('find.details.summary')}</summary>
                            <div className="finding-details-body">
                              {finding.impact && (
                                <div className="finding-field">
                                  <span>{t('find.impact')}</span>
                                  {finding.impact}
                                </div>
                              )}
                              {finding.remediation && (
                                <div className="finding-field">
                                  <span>{t('find.remediation')}</span>
                                  {finding.remediation}
                                </div>
                              )}
                            </div>
                          </details>
                        )}

                        {evidenceIds.length > 0 && (
                          <div className="finding-evidence">
                            {evidenceIds.map((evidenceId) => (
                              <Tag key={evidenceId}>
                                <LinkSimple size={11} weight="bold" />
                                {evidenceById[evidenceId]?.tool ?? 'evidence'} · {shortEvidenceId(evidenceId)}
                              </Tag>
                            ))}
                            {assetCount > 0 && <Tag>{t('find.assetCount').replace('{n}', String(assetCount))}</Tag>}
                          </div>
                        )}

                        <div className="finding-actions">
                          <span className="finding-actions-label">{t('drawer.trace.status')}</span>
                          <SegmentedControl
                            options={statusOptions()}
                            value={(finding.status as FindingStatus) || 'pending'}
                            onChange={(value) => changeStatus(finding, value)}
                            ariaLabel={t('find.status.ariaFor').replace('{name}', finding.title)}
                            className={STATUS_CLASS[(finding.status as FindingStatus) ?? 'pending']}
                          />
                        </div>
                      </article>
                    )
                  })}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
