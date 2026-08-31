import { useEffect, useState, type ReactNode } from 'react'
import { CaretDown, Plus, SidebarSimple, Sparkle, Trash } from '@phosphor-icons/react'
import { listSkills, listTools, understandWorkflow } from './api'
import { t, useLang } from './i18n'
import { Button } from './components/ui/Button'
import { ReadOnlySummary } from './components/ui/ReadOnlySummary'
import { SegmentedControl } from './components/ui/SegmentedControl'
import WorkflowGraph, { conditionText, deriveEdges } from './components/WorkflowGraph'
import { newToolBindingId, toolBindingKey } from './lib/toolBinding'
import { nextStageId } from './stageIds'
import { diffTemplates } from './templateDiff'
import type { Skill, Template, Tool } from './types'

interface Gate {
  name: string
  check: Record<string, unknown>
  on_fail?: 'block' | 'warn'
}

interface PendingApply {
  template: Template
  issues: { severity: string; where: string; message: string }[]
}

interface Props {
  template: Template
  onTemplateChange: (t: Template) => void
  onSave: (t?: Template) => void
}

function ConditionEditor({ value, onChange }: { value: Record<string, unknown> | null | undefined; onChange: (v: Record<string, unknown> | null) => void }) {
  const [text, setText] = useState(value ? JSON.stringify(value, null, 2) : '')
  return (
    <div className="field">
      <span>{t('des.condition')}</span>
      <textarea
        className="textarea"
        rows={3}
        placeholder={t('des.condition.placeholder')}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          const trimmed = e.target.value.trim()
          if (!trimmed) {
            onChange(null)
            return
          }
          try {
            const parsed = JSON.parse(trimmed)
            if (parsed && typeof parsed === 'object') onChange(parsed)
          } catch {
            // invalid JSON: keep local text, only commit valid objects
          }
        }}
      />
    </div>
  )
}

function GateCheckEditor({ value, onChange }: { value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const [text, setText] = useState(JSON.stringify(value ?? {}, null, 2))
  return (
    <textarea
      className="textarea"
      rows={2}
      placeholder='{"op":"truthy","key":"subfinder.subdomains"}'
      value={text}
      onChange={(e) => {
        setText(e.target.value)
        try {
          const parsed = JSON.parse(e.target.value)
          if (parsed && typeof parsed === 'object') onChange(parsed)
        } catch {
          // invalid JSON: keep local text
        }
      }}
    />
  )
}

function GatesEditor({ gates, onChange }: { gates: Gate[]; onChange: (g: Gate[]) => void }) {
  const patch = (index: number, field: 'name' | 'on_fail', v: string) =>
    onChange(gates.map((g, i) => (i === index ? { ...g, [field]: v } : g)))
  const patchCheck = (index: number, check: Record<string, unknown>) =>
    onChange(gates.map((g, i) => (i === index ? { ...g, check } : g)))
  const add = () =>
    onChange([...gates, { name: `gate-${gates.length + 1}`, check: { op: 'truthy', key: '' }, on_fail: 'block' }])
  const remove = (index: number) => onChange(gates.filter((_, i) => i !== index))
  return (
    <div className="field">
      <span>{t('des.gates')}</span>
      {gates.length === 0 && <p className="muted inspector-hint">{t('des.gates.empty')}</p>}
      {gates.map((g, i) => (
        <div key={i} className="binding-card">
          <div className="binding-row">
            <input className="input" value={g.name} onChange={(e) => patch(i, 'name', e.target.value)} />
            <select className="select" value={g.on_fail ?? 'block'} onChange={(e) => patch(i, 'on_fail', e.target.value as 'block' | 'warn')}>
              <option value="block">block</option>
              <option value="warn">warn</option>
            </select>
            <Button size="sm" variant="danger" onClick={() => remove(i)}>
              {t('des.remove')}
            </Button>
          </div>
          <GateCheckEditor value={g.check} onChange={(check) => patchCheck(i, check)} />
        </div>
      ))}
      <Button size="sm" variant="secondary" onClick={add}>
        {t('des.gates.add')}
      </Button>
    </div>
  )
}

function InspectorSection({ title, defaultOpen = true, children }: { title: string; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="inspector-section">
      <button type="button" className="inspector-section-toggle" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <span className="inspector-section-title">{title}</span>
        <CaretDown size={13} weight="bold" className={`inspector-section-chevron${open ? ' open' : ''}`} />
      </button>
      {open && <div className="inspector-section-body">{children}</div>}
    </section>
  )
}

export default function Designer({ template, onTemplateChange, onSave }: Props) {
  useLang()
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(template.start)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [availableTools, setAvailableTools] = useState<Tool[]>([])
  const [availableSkills, setAvailableSkills] = useState<Skill[]>([])
  const [toolToAdd, setToolToAdd] = useState('')
  const [skillToAdd, setSkillToAdd] = useState('')
  const [connectTarget, setConnectTarget] = useState('')
  const [reviewIssues, setReviewIssues] = useState<{ severity: string; where: string; message: string }[] | null>(null)
  const [reviewing, setReviewing] = useState(false)
  const [reviewError, setReviewError] = useState('')
  const [pending, setPending] = useState<PendingApply | null>(null)
  const [inspectorOpen, setInspectorOpen] = useState(true)
  const [inspectorTab, setInspectorTab] = useState<'info' | 'parts' | 'connections'>('info')

  const selectedNode = template.stages.find((s) => s.id === selectedNodeId)
  const selectedEdge = deriveEdges(template).find((e) => e.id === selectedEdgeId)
  const nodeIndex = selectedNode ? template.stages.findIndex((s) => s.id === selectedNode.id) : -1
  const diff = pending ? diffTemplates(template, pending.template) : null

  useEffect(() => {
    listTools().then((r) => setAvailableTools(r.tools))
    listSkills().then((r) => setAvailableSkills(r.skills))
  }, [])

  function patchStageField(stageId: string, field: 'name' | 'goal' | 'timeout' | 'completion' | 'condition' | 'gates', value: unknown) {
    onTemplateChange({
      ...template,
      stages: template.stages.map((s) => (s.id === stageId ? { ...s, [field]: value } : s)),
    })
  }

  function patchNode(field: 'name' | 'goal' | 'timeout' | 'completion' | 'condition' | 'gates', value: unknown) {
    if (!selectedNode) return
    patchStageField(selectedNode.id, field, value)
  }

  function addStage() {
    const id = nextStageId(template.stages)
    const depends_on = selectedNode ? [selectedNode.id] : []
    onTemplateChange({ ...template, stages: [...template.stages, { id, name: t('des.stage.defaultName'), goal: '', depends_on }] })
    setSelectedNodeId(id)
    setSelectedEdgeId(null)
  }

  function removeStage() {
    if (!selectedNode || selectedNode.id === template.start) return
    onTemplateChange({
      ...template,
      stages: template.stages
        .filter((s) => s.id !== selectedNode.id)
        .map((s) => ({ ...s, depends_on: (s.depends_on ?? []).filter((d) => d !== selectedNode.id) })),
    })
    setSelectedNodeId(null)
  }

  function addTool() {
    if (!selectedNode || !toolToAdd) return
    const tools = [...(selectedNode.tools ?? []), { tool: toolToAdd, key: newToolBindingId(), note: '' }]
    onTemplateChange({
      ...template,
      stages: template.stages.map((s) => (s.id === selectedNode.id ? { ...s, tools } : s)),
    })
    setToolToAdd('')
  }

  function removeTool(toolKey: string) {
    if (!selectedNode) return
    const tools = (selectedNode.tools ?? []).filter((b) => toolBindingKey(b) !== toolKey)
    onTemplateChange({
      ...template,
      stages: template.stages.map((s) => (s.id === selectedNode.id ? { ...s, tools } : s)),
    })
  }

  function patchBinding(toolKey: string, field: 'condition' | 'defaults' | 'args_from' | 'enabled' | 'note', value: unknown) {
    if (!selectedNode) return
    const tools = (selectedNode.tools ?? []).map((b) => (toolBindingKey(b) === toolKey ? { ...b, [field]: value } : b))
    onTemplateChange({
      ...template,
      stages: template.stages.map((s) => (s.id === selectedNode.id ? { ...s, tools } : s)),
    })
  }

  function addSkill() {
    if (!selectedNode || !skillToAdd) return
    const skills = [...(selectedNode.skills ?? []), { skill: skillToAdd }]
    onTemplateChange({
      ...template,
      stages: template.stages.map((s) => (s.id === selectedNode.id ? { ...s, skills } : s)),
    })
    setSkillToAdd('')
  }

  function removeSkill(name: string) {
    if (!selectedNode) return
    const skills = (selectedNode.skills ?? []).filter((sb) => sb.skill !== name)
    onTemplateChange({
      ...template,
      stages: template.stages.map((s) => (s.id === selectedNode.id ? { ...s, skills } : s)),
    })
  }

  function patchSkillBinding(name: string, enabled: boolean) {
    if (!selectedNode) return
    const skills = (selectedNode.skills ?? []).map((sb) => (sb.skill === name ? { ...sb, enabled } : sb))
    onTemplateChange({
      ...template,
      stages: template.stages.map((s) => (s.id === selectedNode.id ? { ...s, skills } : s)),
    })
  }

  function addConnection() {
    if (!selectedNode || !connectTarget) return
    onTemplateChange({
      ...template,
      stages: template.stages.map((s) =>
        s.id === connectTarget
          ? {
              ...s,
              depends_on: Array.from(new Set([...(s.depends_on ?? []), selectedNode.id])),
            }
          : s,
      ),
    })
    setConnectTarget('')
  }

  function removeConnection(id: string) {
    const edge = deriveEdges(template).find((e) => e.id === id)
    if (!edge) return
    onTemplateChange({
      ...template,
      stages: template.stages.map((s) =>
        s.id === edge.target ? { ...s, depends_on: (s.depends_on ?? []).filter((d) => d !== edge.source) } : s,
      ),
    })
    setSelectedEdgeId(null)
  }

  async function aiUnderstandSave() {
    setReviewing(true)
    setReviewError('')
    setReviewIssues(null)
    setPending(null)
    try {
      const { template: updated, issues } = await understandWorkflow(template)
      setPending({ template: updated, issues })
    } catch (e) {
      setReviewError(String(e))
    } finally {
      setReviewing(false)
    }
  }

  function confirmAiSave() {
    if (!pending) return
    onTemplateChange(pending.template)
    setReviewIssues(pending.issues)
    setPending(null)
    onSave(pending.template)
  }

  function cancelAiSave() {
    setPending(null)
  }

  function renderInspector() {
    let body: ReactNode

    if (pending && diff) {
      body = (
        <div className="card ai-preview">
          <div className="ai-preview-header">
            <b>{t('des.aipreview')}</b>
          </div>
          {diff.changedConnections.length > 0 && (
            <div className="ai-preview-block">
              <div className="muted ai-preview-label">{t('des.aipreview.depchanges')}</div>
              {diff.changedConnections.map((c) => (
                <div key={c.id} className="ai-preview-row">
                  <b>{c.id}</b>
                  {t('des.aipreview.change')
                    .replace('{before}', c.before.length ? c.before.join(', ') : t('des.none'))
                    .replace('{after}', c.after.length ? c.after.join(', ') : t('des.none'))}
                </div>
              ))}
            </div>
          )}
          {diff.summaryBefore !== diff.summaryAfter && (
            <div className="ai-preview-block">
              <div className="muted ai-preview-label">{t('des.aipreview.summaryupdated')}</div>
              <pre className="ai-preview-pre">{diff.summaryAfter}</pre>
            </div>
          )}
          {pending.issues.length === 0 ? (
            <p className="muted ai-preview-block">{t('des.issues.none')}</p>
          ) : (
            <ul className="ai-preview-list">
              {pending.issues.map((iss, i) => (
                <li key={i} className="ai-preview-row">
                  <b>{iss.where}</b> [{iss.severity}] {iss.message}
                </li>
              ))}
            </ul>
          )}
          <div className="ai-preview-actions">
            <Button size="sm" variant="primary" onClick={confirmAiSave}>
              {t('des.confirm.save')}
            </Button>
            <Button size="sm" onClick={cancelAiSave}>
              {t('common.cancel')}
            </Button>
          </div>
        </div>
      )
    } else if (selectedNode) {
      const outgoing = deriveEdges(template).filter((edge) => edge.source === selectedNode.id)
      body = (
        <>
          <div className="inspector-heading">
            <h3>{selectedNode.name}</h3>
            <div className="muted">
              {t('des.step').replace('{n}', String(nodeIndex + 1))}
              {nodeIndex === 0 ? t('des.stage.start') : nodeIndex === template.stages.length - 1 ? t('des.stage.end') : ''}
            </div>
          </div>

          <SegmentedControl
            className="inspector-tabs"
            options={[
              { value: 'info', label: t('des.tab.info') },
              { value: 'parts', label: t('des.tab.parts') },
              { value: 'connections', label: t('des.tab.connections') },
            ]}
            value={inspectorTab}
            onChange={(value) => setInspectorTab(value)}
            ariaLabel={t('des.inspector.aria')}
          />

          {inspectorTab === 'info' && (
            <InspectorSection title={t('des.tab.info')}>
              <div className="field">
                <span>{t('des.name')}</span>
                <input className="input" value={selectedNode.name} onChange={(e) => patchNode('name', e.target.value)} />
              </div>
              <div className="field">
                <span>{t('des.step.label')}</span>
                <div className="muted">{t('des.step').replace('{n}', String(nodeIndex + 1))}</div>
              </div>
              <div className="field">
                <span>{t('des.goal')}</span>
                <textarea className="textarea" rows={3} value={selectedNode.goal ?? ''} onChange={(e) => patchNode('goal', e.target.value)} />
              </div>
              <div className="field">
                <span>{t('des.timeout')}</span>
                <input className="input" type="number" value={selectedNode.timeout ?? 300} onChange={(e) => patchNode('timeout', Number(e.target.value))} />
              </div>
              <ConditionEditor key={`cond-${selectedNode.id}`} value={selectedNode.condition ?? null} onChange={(v) => patchNode('condition', v)} />
              <GatesEditor key={`gates-${selectedNode.id}`} gates={selectedNode.gates ?? []} onChange={(gates) => patchNode('gates', gates)} />
              <div className="field">
                <ReadOnlySummary title={t('des.completion')} value={selectedNode.completion ?? null} />
              </div>
              <div className="field">
                <span>{t('des.response')}</span>
                <div className="muted">{t('des.response.desc')}</div>
              </div>
            </InspectorSection>
          )}

          {inspectorTab === 'parts' && (
            <>
              <InspectorSection title={t('des.tools.title')}>
                {(selectedNode.tools ?? []).map((b) => {
                  const bindingKey = toolBindingKey(b)
                  return (
                    <div key={bindingKey} className="binding-card">
                      <div className="binding-row">
                        <b>{b.tool}</b>
                        <div className="binding-actions">
                          <label className="check-label">
                            <input type="checkbox" checked={b.enabled ?? true} onChange={(e) => patchBinding(bindingKey, 'enabled', e.target.checked)} />
                            {t('des.enabled')}
                          </label>
                          <Button size="sm" variant="danger" onClick={() => removeTool(bindingKey)}>
                            {t('des.remove')}
                          </Button>
                        </div>
                      </div>
                      <input className="input" placeholder={t('des.tool.note.placeholder')} value={b.note ?? ''} onChange={(e) => patchBinding(bindingKey, 'note', e.target.value)} />
                      <div className="field binding-editor">
                        <ReadOnlySummary title={t('des.binding.condition')} value={b.condition ?? null} />
                      </div>
                      <div className="field">
                        <ReadOnlySummary title={t('des.binding.defaults')} value={b.defaults ?? {}} />
                      </div>
                      <div className="field">
                        <ReadOnlySummary title="args_from" value={b.args_from ?? {}} />
                      </div>
                    </div>
                  )
                })}
                <div className="add-select-row">
                  <select className="select" value={toolToAdd} onChange={(e) => setToolToAdd(e.target.value)}>
                    <option value="" disabled>
                      {t('des.select.tool')}
                    </option>
                    {availableTools.map((tool) => (
                      <option key={tool.name} value={tool.name}>
                        {tool.name}
                      </option>
                    ))}
                  </select>
                  <Button onClick={addTool}>{t('des.add')}</Button>
                </div>
              </InspectorSection>

              <InspectorSection title={t('des.skills.title')}>
                {(selectedNode.skills ?? []).map((sb) => (
                  <div key={sb.skill} className="skill-row">
                    <b>{sb.skill}</b>
                    <div className="binding-actions">
                      <label className="check-label">
                        <input type="checkbox" checked={sb.enabled ?? true} onChange={(e) => patchSkillBinding(sb.skill, e.target.checked)} />
                        {t('des.enabled')}
                      </label>
                      <Button size="sm" variant="danger" onClick={() => removeSkill(sb.skill)}>
                        {t('des.remove')}
                      </Button>
                    </div>
                  </div>
                ))}
                <div className="add-select-row">
                  <select className="select" value={skillToAdd} onChange={(e) => setSkillToAdd(e.target.value)}>
                    <option value="" disabled>
                      {t('des.select.skill')}
                    </option>
                    {availableSkills.map((s) => (
                      <option key={s.name} value={s.name}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                  <Button onClick={addSkill}>{t('des.add')}</Button>
                </div>
              </InspectorSection>
            </>
          )}

          {inspectorTab === 'connections' && (
            <InspectorSection title={t('des.tab.connections')}>
              {outgoing.length === 0 ? (
                <p className="muted inspector-hint">{t('des.connections.empty')}</p>
              ) : (
                outgoing.map((edge) => (
                  <div key={edge.id} className="connection-row">
                    <div className="connection-path">
                      <b>{template.stages.find((s) => s.id === edge.source)?.name ?? edge.source}</b>
                      <span className="muted"> → </span>
                      <b>{template.stages.find((s) => s.id === edge.target)?.name ?? edge.target}</b>
                    </div>
                    <button className="connection-delete" aria-label={t('des.connection.delete')} onClick={() => removeConnection(edge.id)}>
                      <Trash size={14} weight="bold" />
                    </button>
                  </div>
                ))
              )}
              <div className="inspector-divider" />
              <select className="select inspector-field-input" value={connectTarget} onChange={(e) => setConnectTarget(e.target.value)}>
                <option value="" disabled>
                  {t('des.select.target.stage')}
                </option>
                {template.stages
                  .filter((s) => s.id !== selectedNode.id)
                  .map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
              </select>
              <Button onClick={addConnection}>{t('des.connection.add')}</Button>
              <div className="inspector-divider" />
              <div className="stage-actions">
                <Button variant="danger" onClick={removeStage} disabled={selectedNode.id === template.start}>
                  {t('des.stage.delete')}
                </Button>
              </div>
            </InspectorSection>
          )}
        </>
      )
    } else if (selectedEdge) {
      const targetStage = template.stages.find((s) => s.id === selectedEdge.target)
      body = (
        <>
          <div className="inspector-heading">
            <h3>{t('des.dependency')}</h3>
            <div className="muted">
              {template.stages.find((s) => s.id === selectedEdge.source)?.name ?? selectedEdge.source} →{' '}
              {targetStage?.name ?? selectedEdge.target}
            </div>
          </div>
          <InspectorSection title={t('des.trigger')}>
            <p className="muted inspector-hint" style={{ marginTop: 0 }}>
              {selectedEdge.condition ? conditionText(selectedEdge.condition) : t('des.no.condition')}
            </p>
            {targetStage && (
              <ConditionEditor
                key={`edge-cond-${targetStage.id}`}
                value={targetStage.condition ?? null}
                onChange={(v) => patchStageField(targetStage.id, 'condition', v)}
              />
            )}
          </InspectorSection>
          <InspectorSection title={t('des.dep.info')}>
            <Button variant="danger" onClick={() => removeConnection(selectedEdge.id)}>
              {t('des.connection.delete')}
            </Button>
          </InspectorSection>
        </>
      )
    } else {
      body = <p className="muted inspector-hint">{t('des.hint')}</p>
    }

    return (
      <>
        {body}
        {reviewError && <p className="inspector-error">{reviewError}</p>}
        {reviewIssues && !pending && (
          <div className="inspector-review">
            <h4 className="inspector-review-title">{t('des.review.title')}</h4>
            {reviewIssues.length === 0 ? (
              <p className="muted">{t('des.issues.none')}</p>
            ) : (
              <ul className="issue-list">
                {reviewIssues.map((iss, i) => (
                  <li key={i} className={`issue-item ${iss.severity === 'error' ? 'error' : 'warning'}`}>
                    <b>{iss.where}</b> <span className="muted">[{iss.severity}]</span>
                    <div className="issue-message">{iss.message}</div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </>
    )
  }

  return (
    <div className="page">
      <div className="designer-toolbar">
        <span className="muted">{t('des.title')}</span>
        <div className="designer-toolbar-actions">
          <Button size="sm" variant="ghost" icon={<Plus size={15} weight="bold" />} onClick={addStage}>
            {t('des.stage.add')}
          </Button>
          <Button size="sm" variant="ghost" icon={<SidebarSimple size={15} weight="bold" />} onClick={() => setInspectorOpen(!inspectorOpen)}>
            {inspectorOpen ? t('des.panel.collapse') : t('des.panel.expand')}
          </Button>
          <Button size="sm" variant="primary" icon={<Sparkle size={15} weight="bold" />} loading={reviewing} onClick={aiUnderstandSave}>
            {reviewing ? t('des.ai.working') : t('des.ai.understand')}
          </Button>
        </div>
      </div>

      <div className="designer-body">
        <div className="designer-canvas">
          <WorkflowGraph
            template={template}
            selectedNodeId={selectedNodeId}
            selectedEdgeId={selectedEdgeId}
            onNodeClick={(id) => {
              setSelectedNodeId(id)
              setSelectedEdgeId(null)
            }}
            onEdgeClick={(id) => {
              setSelectedEdgeId(id)
              setSelectedNodeId(null)
            }}
          />
        </div>

        {inspectorOpen && <aside className="designer-inspector">{renderInspector()}</aside>}
      </div>
    </div>
  )
}
