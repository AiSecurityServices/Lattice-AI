import { useEffect, useState } from 'react'
import { Copy } from '@phosphor-icons/react'
import { applyWorkflowSuggestion, listFindings, saveTemplate } from '../api'
import { t, useLang } from '../i18n'
import type { EvolutionReport, EvolutionSuggestion, RunDetail, RunResult, Template } from '../types'
import { Button } from './ui/Button'
import { ConfirmDialog } from './ui/ConfirmDialog'
import { SeverityBadge } from './ui/SeverityBadge'
import { Tag } from './ui/Tag'

type ReportRun = RunResult | RunDetail

function isDetail(run: ReportRun): run is RunDetail {
  return 'target' in run
}

function factText(facts: Record<string, unknown>): string {
  const entries = Object.entries(facts)
  if (entries.length === 0) return t('rrep.facts.empty')
  return entries.map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`).join('\n')
}

function riskSeverity(risk: unknown): string {
  const value = String(risk)
  if (value === 'critical' || value === 'high' || value === 'medium' || value === 'low' || value === 'info') return value
  if (value === 'warning') return 'medium'
  return 'info'
}

function buildMarkdown(e: EvolutionReport): string {
  const lines: string[] = [`# ${t('rrep.md.title')}`]
  if (e.summary) lines.push(e.summary)
  for (const step of e.steps ?? []) {
    lines.push('', `### ${step.label}`, ...(step.difficulties ?? []).map((d) => `- ${t('rrep.md.difficulty').replace('{text}', d)}`),
      ...(step.conflicts ?? []).map((c) => `- ${t('rrep.md.conflict').replace('{text}', c)}`), ...(step.misunderstandings ?? []).map((m) => `- ${t('rrep.md.misunderstanding').replace('{text}', m)}`))
  }
  lines.push('', `## ${t('rrep.suggestions')}`)
  for (const s of e.suggestions ?? []) lines.push(`- [${s.type}] ${s.detail ?? ''}`)
  lines.push('', `## ${t('rrep.unresolved')}`)
  for (const u of e.unresolved ?? []) lines.push(`- ${u}`)
  if (e.confidence) lines.push('', t('rrep.confidence').replace('{value}', String(e.confidence)))
  return lines.join('\n')
}

export interface GroundingStats {
  verified: number
  unverified: number
  missing_evidence: number
}

/** Counts match report_export.build_report_data: buckets over every finding
 * of the run that carries a grounding verdict. */
export function groundingStatsOf(findings: Array<{ run_id?: string; grounding?: { status?: string } }>): GroundingStats {
  const counts: GroundingStats = { verified: 0, unverified: 0, missing_evidence: 0 }
  for (const finding of findings) {
    const status = finding.grounding?.status
    if (status === 'verified' || status === 'unverified' || status === 'missing_evidence') {
      counts[status] += 1
    }
  }
  return counts
}

export function RunReport({
  run,
  templateId,
  workflowTemplate,
  onTemplateUpdated,
}: {
  run: ReportRun
  templateId?: string
  workflowTemplate?: Template | null
  onTemplateUpdated?: () => void
}) {
  useLang()
  const [tab, setTab] = useState<'report' | 'selfcheck'>('report')
  const [confirming, setConfirming] = useState<EvolutionSuggestion | null>(null)
  const [busy, setBusy] = useState(false)
  const [applyError, setApplyError] = useState('')
  const [undoTemplate, setUndoTemplate] = useState<Template | null>(null)
  const [grounding, setGrounding] = useState<GroundingStats | null>(null)
  const reportText = run.report || factText(run.facts)
  const evolutionMarkdown = run.evolution ? buildMarkdown(run.evolution) : ''
  const showTabs = !!run.evolution

  useEffect(() => {
    let alive = true
    listFindings()
      .then(({ findings }) => {
        if (alive) setGrounding(groundingStatsOf(findings.filter((f) => f.run_id === run.id)))
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [run.id])

  async function applyConfirmed() {
    if (!confirming || !templateId) return
    setBusy(true)
    setApplyError('')
    try {
      if (workflowTemplate) setUndoTemplate(workflowTemplate)
      await applyWorkflowSuggestion(templateId, confirming as unknown as Record<string, unknown>)
      setConfirming(null)
      onTemplateUpdated?.()
    } catch (caught) {
      setApplyError(String(caught))
    } finally {
      setBusy(false)
    }
  }

  async function undoApplied() {
    if (!templateId || !undoTemplate) return
    setBusy(true)
    setApplyError('')
    try {
      await saveTemplate(templateId, undoTemplate)
      setUndoTemplate(null)
      onTemplateUpdated?.()
    } catch (caught) {
      setApplyError(String(caught))
    } finally {
      setBusy(false)
    }
  }

  function renderEvolution(e?: EvolutionReport) {
    if (!e) return <div className="muted">{t('rrep.evolution.empty')}</div>
    return (
      <div className="self-check-report">
        <h4>{t('rrep.summary')}</h4>
        <p>{e.summary || t('rrep.summary.empty')}</p>
        <h4>{t('rrep.suggestions')}</h4>
        <ul>
          {(e.suggestions ?? []).map((s, i) => (
            <li key={i}>
              <div>[{s.type}] {s.detail ?? ''}</div>
              {s.stage_id && <div className="muted">{t('rrep.stage')}{s.stage_id}</div>}
              {s.tool_name && <div className="muted">{t('rrep.tool')}{s.tool_name}</div>}
              {templateId && (
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => setConfirming(s)}>
                  {t('rrep.applyToTemplate')}
                </Button>
              )}
            </li>
          ))}
        </ul>
        {undoTemplate && (
          <Button size="sm" variant="danger" disabled={busy} onClick={() => void undoApplied()}>
            {t('rrep.undoApply')}
          </Button>
        )}
        <h4>{t('rrep.unresolved')}</h4>
        <ul>{(e.unresolved ?? []).map((u, i) => <li key={i}>{u}</li>)}</ul>
        {e.confidence && <p className="muted">{t('rrep.confidence').replace('{value}', String(e.confidence))}</p>}
      </div>
    )
  }

  return (
    <article className="report">
      {showTabs && (
        <div className="report-tabs">
          <button type="button" className={tab === 'report' ? 'active' : ''} onClick={() => setTab('report')}>
            {t('rrep.tab.report')}
          </button>
          <button type="button" className={tab === 'selfcheck' ? 'active' : ''} onClick={() => setTab('selfcheck')}>
            {t('rrep.tab.selfcheck')}
          </button>
        </div>
      )}
      <div className="report-bar">
        <div className="report-meta">
          {isDetail(run) && <Tag tone="primary">{run.target}</Tag>}
          {run.facts?.risk != null && (
            <SeverityBadge severity={riskSeverity(run.facts.risk)}>{t('rrep.risk')}{String(run.facts.risk)}</SeverityBadge>
          )}
          {grounding && grounding.verified + grounding.unverified + grounding.missing_evidence > 0 && (
            <span className="muted gnd-summary">
              {t('gnd.summary')}{t('rrep.colon')}{t('gnd.status.verified')} {grounding.verified} /{' '}
              {t('gnd.status.unverified')} {grounding.unverified} / {t('gnd.status.missing_evidence')}{' '}
              {grounding.missing_evidence}
            </span>
          )}
          {isDetail(run) && run.created_at && <span className="muted">{run.created_at.replace('T', ' ')}</span>}
        </div>
        <Button
          size="sm"
          variant="ghost"
          aria-label={t('rrep.copyReport')}
          icon={<Copy size={14} weight="bold" />}
          onClick={() => navigator.clipboard?.writeText(tab === 'selfcheck' ? evolutionMarkdown : reportText)}
        />
      </div>
      {applyError && <div className="text-danger">{applyError}</div>}
      {tab === 'report' ? <div className="report-summary">{reportText}</div> : renderEvolution(run.evolution)}
      <details className="report-timeline">
        <summary>{t('rrep.timeline')}</summary>
        <ul className="timeline">
          {run.events.map((event) => (
            <li key={`${run.id}-${event.seq}`} className="timeline-item">
              <span className="timeline-type">{event.type}</span>
              <span className="timeline-data">{JSON.stringify(event.data)}</span>
            </li>
          ))}
        </ul>
      </details>
      <ConfirmDialog
        open={!!confirming}
        title={t('rrep.apply.title')}
        description={t('rrep.apply.body').replace('{template}', String(templateId ?? ''))}
        confirmLabel={t('evo.card.apply')}
        onConfirm={() => void applyConfirmed()}
        onCancel={() => setConfirming(null)}
      />
    </article>
  )
}
