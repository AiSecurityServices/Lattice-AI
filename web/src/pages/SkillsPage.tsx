import { useEffect, useState } from 'react'
import { Lightbulb, MagnifyingGlass, Plus } from '@phosphor-icons/react'
import { createSkill, deleteSkill, listGroups, listSkills, setGroupMembers, updateSkill, type GroupsPayload } from '../api'
import { AssetGroups } from '../components/AssetGroups'
import { ApplyToWorkflowDialog } from '../components/ui/ApplyToWorkflowDialog'
import { Button } from '../components/ui/Button'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'
import { SegmentedControl } from '../components/ui/SegmentedControl'
import { t, useLang } from '../i18n'
import type { Skill, Template } from '../types'

export default function SkillsPage({
  activeTemplate,
  refreshKey,
  onTemplateUpdated,
}: {
  activeTemplate: Template | null
  refreshKey: number
  onTemplateUpdated?: () => void
}) {
  useLang()
  const [skills, setSkills] = useState<Skill[]>([])
  const [groups, setGroups] = useState<GroupsPayload>({ tool_groups: [], skill_groups: [] })
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [previewing, setPreviewing] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('')
  const [content, setContent] = useState('')
  const [tagsText, setTagsText] = useState('')
  const [confirming, setConfirming] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [applying, setApplying] = useState<{ kind: 'skill'; items: string[] } | null>(null)
  const [view, setView] = useState<'assets' | 'groups'>('assets')

  async function load() {
    const [skillResult, groupResult] = await Promise.all([listSkills(), listGroups()])
    setSkills(skillResult.skills)
    setGroups(groupResult)
  }

  useEffect(() => {
    load()
  }, [refreshKey])

  function resetForm() {
    setName('')
    setDescription('')
    setCategory('')
    setContent('')
    setTagsText('')
    setEditing(null)
    setShowForm(false)
  }

  function startEdit(s: Skill) {
    setName(s.name)
    setDescription(s.description ?? '')
    setCategory(s.category ?? '')
    setContent(s.content ?? '')
    setTagsText((s.tags ?? []).join(', '))
    setEditing(s.name)
    setShowForm(true)
  }

  async function save() {
    if (!name) return
    const tags = tagsText.split(',').map((t) => t.trim()).filter(Boolean)
    if (editing) {
      await updateSkill(editing, { name, description, category, tags, content })
    } else {
      await createSkill({ name, description, category, tags, content })
    }
    resetForm()
    load()
  }

  function requestRemove(n: string) {
    setConfirming(n)
  }

  async function removeConfirmed() {
    if (!confirming) return
    const name = confirming
    setConfirming(null)
    await deleteSkill(name)
    load()
  }

  async function addSkillToGroup(skillName: string, groupId: string) {
    const group = groups.skill_groups.find((g) => g.id === groupId)
    if (!group) return
    const members = group.members.includes(skillName) ? group.members : [...group.members, skillName]
    await setGroupMembers('skill', groupId, members)
    setGroups(await listGroups())
  }

  async function addToGlobal(s: Skill) {
    if (skills.some((item) => item.name === s.name)) return
    await createSkill({ name: s.name, description: s.description ?? '', category: s.category ?? '', tags: s.tags ?? [], content: s.content ?? '' })
    load()
  }

  const templateSkillNames = new Set(
    (activeTemplate?.stages ?? []).flatMap((s) => (s.skills ?? []).map((sb) => sb.skill)),
  )
  const templateSkillDefs = activeTemplate?.skills ?? []
  const boundSkills = Array.from(templateSkillNames)
    .map((name) => templateSkillDefs.find((s) => s.name === name) ?? skills.find((s) => s.name === name))
    .filter((s): s is Skill => Boolean(s))
  const query = search.trim().toLowerCase()
  const filteredSkills = skills.filter((s) => `${s.name} ${s.description ?? ''}`.toLowerCase().includes(query))

  return (
    <div className="page">
      <div className="page-heading">
        <h2 className="page-heading-title">{t('skp.title')}</h2>
        <div className="page-heading-actions">
          <SegmentedControl
            options={[
              { value: 'assets', label: 'Skill' },
              { value: 'groups', label: t('skp.tab.groups') },
            ]}
            value={view}
            onChange={(value) => setView(value)}
            ariaLabel={t('skp.viewAria')}
          />
          <label className="search-input">
            <MagnifyingGlass size={14} weight="bold" />
            <input className="input" placeholder={t('skp.searchPlaceholder')} value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
          <Button size="sm" variant="primary" icon={<Plus size={15} weight="bold" />} onClick={() => (showForm ? resetForm() : setShowForm(true))}>
            {showForm ? t('common.cancel') : t('skp.add')}
          </Button>
        </div>
      </div>

      <div className="page-body">
        {showForm && (
          <div className="card card-gap">
            <h4 style={{ margin: '0 0 12px' }}>{editing ? t('skp.editTitle') : t('skp.createTitle')}</h4>
            <div className="field">
              <span>{t('nd.name')}</span>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} disabled={!!editing} />
            </div>
            <div className="field">
              <span>{t('skp.description')}</span>
              <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <div className="field">
              <span>{t('imp.save.category')}</span>
              <input className="input" value={category} onChange={(e) => setCategory(e.target.value)} />
            </div>
            <div className="field">
              <span>{t('skp.tagsLabel')}</span>
              <input className="input" value={tagsText} onChange={(e) => setTagsText(e.target.value)} />
            </div>
            <div className="field">
              <span>{t('skp.contentLabel')}</span>
              <textarea className="textarea mono-area" value={content} onChange={(e) => setContent(e.target.value)} style={{ height: 140 }} />
            </div>
            <Button variant="primary" onClick={save}>
              {t('common.save')}
            </Button>
          </div>
        )}

        {boundSkills.length > 0 && (
          <div className="asset-group">
            <div className="section-toolbar">
              <h4 className="section-label">{t('skp.templateSkills')}</h4>
            </div>
            <div className="skill-grid">
              {boundSkills.map((s) => (
                <div key={s.name} className="card skill-card">
                  <div className="skill-card-head">
                    <div className="skill-card-title">
                      <span className="card-icon" aria-hidden>
                        <Lightbulb size={15} weight="bold" />
                      </span>
                      {s.name}
                    </div>
                    <div className="card-actions">
                      <Button size="sm" variant="ghost" onClick={() => startEdit(s)}>
                        {t('skp.edit')}
                      </Button>
                      {!skills.some((item) => item.name === s.name) && (
                        <Button size="sm" variant="ghost" onClick={() => addToGlobal(s)}>
                          {t('skp.addToGlobal')}
                        </Button>
                      )}
                    </div>
                  </div>
                  <div className="card-desc">{s.description}</div>
                  {(s.tags ?? []).length > 0 && (
                    <div className="card-tags">
                      {(s.tags ?? []).map((tag) => (
                        <span key={tag} className="tag">
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {view === 'groups' ? (
          <AssetGroups
            kind="skill"
            groups={groups.skill_groups}
            assets={skills}
            onGroupsChange={(skillGroups) => setGroups((prev) => ({ ...prev, skill_groups: skillGroups }))}
            onApply={(items) => setApplying({ kind: 'skill', items })}
          />
        ) : (
          <div className="asset-group">
            <div className="section-toolbar">
              <h4 className="section-label">{t('skp.globalSkills')}</h4>
            </div>
            {skills.length === 0 ? (
            <div className="empty">
              <div className="empty-title">{t('skp.emptyTitle')}</div>
              <div className="empty-desc">{t('skp.emptyDesc')}</div>
            </div>
          ) : (
            <div className="skill-grid global-skill-grid">
              {filteredSkills.map((s) => (
                <div key={s.name} className="card skill-card">
                  <div className="skill-card-head">
                    <div className="skill-card-title">
                      <span className="card-icon" aria-hidden>
                        <Lightbulb size={15} weight="bold" />
                      </span>
                      {s.name}
                    </div>
                    <div className="card-actions">
                      <Button size="sm" onClick={() => startEdit(s)}>
                        {t('skp.edit')}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setPreviewing(previewing === s.name ? null : s.name)}>
                        {previewing === s.name ? t('skp.collapse') : t('skp.preview')}
                      </Button>
                      <Button size="sm" variant="danger" onClick={() => requestRemove(s.name)}>
                        {t('skp.delete')}
                      </Button>
                    </div>
                  </div>
                  <div className="card-desc">{s.description}</div>
                  {(s.tags ?? []).length > 0 && (
                    <div className="card-tags">
                      {(s.tags ?? []).map((tag) => (
                        <span key={tag} className="tag">
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                  {s.source && (
                    <div className="card-tags">
                      <span className="tag" aria-label={t('skill.source.aria')}>
                        {s.source}
                      </span>
                    </div>
                  )}
                  {s.classification && (s.classification.cve || s.classification.cwe || s.classification.cvss) && (
                    <div className="skill-classification muted">
                      {[s.classification.cve, s.classification.cwe, s.classification.cvss && `CVSS ${s.classification.cvss}`]
                        .filter(Boolean)
                        .join(' · ')}
                    </div>
                  )}
                  {previewing === s.name && (
                    <pre className="mono-area skill-preview">
                      {s.content || t('skp.emptyContent')}
                    </pre>
                  )}
                  <div className="asset-card-actions">
                    <select className="select" value="" aria-label={t('skp.addToGroup')} onChange={(e) => addSkillToGroup(s.name, e.target.value)}>
                      <option value="" disabled>
                        {t('skp.addToGroup')}
                      </option>
                      {groups.skill_groups.map((g) => (
                        <option key={g.id} value={g.id}>
                          {g.name}
                        </option>
                      ))}
                    </select>
                    <Button size="sm" variant="secondary" onClick={() => setApplying({ kind: 'skill', items: [s.name] })}>
                      {t('skp.useInWorkflow')}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      </div>

      <ApplyToWorkflowDialog
        open={!!applying}
        kind={applying?.kind ?? 'skill'}
        items={applying?.items ?? []}
        template={activeTemplate}
        onCancel={() => setApplying(null)}
        onApplied={() => {
          setApplying(null)
          onTemplateUpdated?.()
        }}
      />

      <ConfirmDialog
        open={!!confirming}
        title={t('skp.deleteConfirmTitle')}
        description={t('skp.deleteConfirmDesc').replace('{name}', String(confirming))}
        confirmLabel={t('skp.delete')}
        danger
        onConfirm={removeConfirmed}
        onCancel={() => setConfirming(null)}
      />
    </div>
  )
}
