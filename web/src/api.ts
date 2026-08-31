import type { ApprovalDecision, Asset, AssetGraph, AssistantResult, ChatMessage, ChatResult, DashboardData, DangerPolicy, DangerPreflightItem, Evidence, EvolutionReport, EvolutionSuggestion, Finding, GenerationReport, ImportConfirmFills, ImportInspectResult, ImportPreview, LogLine, MissingTool, ModelList, Preferences, Project, ProviderMeta, ReplayPage, ReportFormat, RunDetail, RunDiff, RunResult, RunSummary, RunWorkflowState, ScopePolicy, ScopePreflight, SelfCheckNote, Session, SessionEvent, Settings, Skill, Template, Tool, ToolchainInfo, ToolchainRegistryEntry } from './types'
import { t } from './i18n'

function authHeaders(): Record<string, string> {
  // Only needed when the backend is reached from a non-loopback peer; the
  // token can be set manually via localStorage.setItem('lattice.token', ...).
  try {
    const token = localStorage.getItem('lattice.token')
    return token ? { 'X-Lattice-Token': token } : {}
  } catch {
    return {}
  }
}

async function request<T>(url: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(init?.headers as Record<string, string> | undefined) },
    signal,
  })
  if (!res.ok) {
    throw new Error(`${res.status}: ${await res.text()}`)
  }
  return res.json() as Promise<T>
}

export function listTemplates(): Promise<{ templates: { id: string; name: string }[] }> {
  return request('/api/templates')
}

export function getTemplate(id: string): Promise<Template> {
  return request(`/api/templates/${id}`)
}

export function saveTemplate(id: string, template: Template): Promise<{ id: string; name: string }> {
  return request(`/api/templates/${id}`, { method: 'PUT', body: JSON.stringify(template) })
}

export function deleteTemplate(id: string): Promise<{ deleted: string }> {
  return request(`/api/templates/${id}`, { method: 'DELETE' })
}

export function cloneTemplate(id: string): Promise<{ id: string; name: string }> {
  return request(`/api/templates/${id}/clone`, { method: 'POST' })
}

export function renameTemplate(id: string, name: string): Promise<{ id: string; name: string }> {
  return request(`/api/templates/${id}/rename`, { method: 'POST', body: JSON.stringify({ name }) })
}

export function runTemplate(template: Template, target: string, autonomous = false, signal?: AbortSignal): Promise<RunResult> {
  return request('/api/run', { method: 'POST', body: JSON.stringify({ template, target, autonomous }) }, signal)
}

export interface RunStreamEvent {
  seq?: number
  type: string
  data?: Record<string, unknown>
  content?: string
  facts?: Record<string, unknown>
  report?: string | null
  evolution?: EvolutionReport
  notes?: SelfCheckNote[]
  step?: { label: string; stage?: string }
  run_id?: string
  id?: string
  message?: string
}

export async function startRun(template: Template, target: string, autonomous = false, selfCheck = false, dangerAllowances: string[] = [], sessionId = '', signal?: AbortSignal): Promise<{ id: string }> {
  return request('/api/runs', { method: 'POST', body: JSON.stringify({ template, target, autonomous, self_check: selfCheck, danger_allowances: dangerAllowances, session_id: sessionId }) }, signal)
}

export function subscribeRunEvents(id: string, onEvent: (event: RunStreamEvent) => void, signal?: AbortSignal): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    const controller = new AbortController()
    const abort = () => controller.abort()
    if (signal?.aborted) {
      reject(new Error(t('apie.cancelled')))
      return
    }
    signal?.addEventListener('abort', abort)

    fetch(`/api/runs/${id}/events`, { headers: { Accept: 'text/event-stream', ...authHeaders() }, signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
        const reader = res.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        const events: SessionEvent[] = []
        let finalResult: RunResult | null = null
        let streamError: Error | null = null
        let fallbackSeq = 0

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          let index
          while ((index = buffer.indexOf('\n\n')) !== -1) {
            const chunk = buffer.slice(0, index)
            buffer = buffer.slice(index + 2)
            for (const line of chunk.split('\n')) {
              if (!line.startsWith('data:')) continue
              const raw = line.slice(5).trim()
              if (!raw) continue
              const event = JSON.parse(raw) as RunStreamEvent
              onEvent(event)
              if (event.type === 'run_complete') {
                finalResult = { id: event.id ?? id, facts: event.facts ?? {}, events, report: event.report ?? null, evolution: event.evolution }
                break
              }
              if (event.type === 'error') {
                streamError = new Error(event.message ?? t('apie.runFailed'))
                break
              }
              if (event.type === 'run_stopped') {
                streamError = new Error(event.message ?? t('apie.runStopped'))
                break
              }
              if (event.seq != null || event.data != null) {
                events.push({ seq: event.seq ?? --fallbackSeq, type: event.type, data: event.data ?? {} })
              }
            }
            if (finalResult || streamError) break
          }
          if (finalResult || streamError) break
        }
        controller.abort()
        if (streamError) reject(streamError)
        else resolve(finalResult ?? { id, facts: {}, events: [], report: null })
      })
      .catch((err) => {
        if (err?.name === 'AbortError' || signal?.aborted) reject(new Error(t('apie.cancelled')))
        else reject(err)
      })
      .finally(() => signal?.removeEventListener('abort', abort))
  })
}

export function runTemplateStream(
  template: Template,
  target: string,
  autonomous: boolean,
  selfCheck: boolean,
  dangerAllowances: string[],
  onEvent: (event: RunStreamEvent) => void,
  signal?: AbortSignal,
  sessionId = '',
): Promise<RunResult> {
  return startRun(template, target, autonomous, selfCheck, dangerAllowances, sessionId, signal).then(({ id }) => subscribeRunEvents(id, onEvent, signal))
}

export function chat(template: Template, message: string, history: ChatMessage[], facts: Record<string, unknown>, signal?: AbortSignal): Promise<ChatResult> {
  return request('/api/chat', { method: 'POST', body: JSON.stringify({ template, message, history, facts }) }, signal)
}

export function assistant(message: string, history: ChatMessage[], confirm?: { tool: string; args: Record<string, unknown> }): Promise<AssistantResult> {
  return request('/api/assistant', { method: 'POST', body: JSON.stringify({ message, history, confirm }) })
}

export function listConversations(): Promise<{ conversations: Session[] }> {
  return request('/api/conversations')
}

export function createConversation(payload: Partial<Session>): Promise<Session> {
  return request('/api/conversations', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateConversation(id: string, payload: Partial<Session>): Promise<Session> {
  return request(`/api/conversations/${id}`, { method: 'PUT', body: JSON.stringify(payload) })
}

export function deleteConversation(id: string): Promise<{ deleted: string }> {
  return request(`/api/conversations/${id}`, { method: 'DELETE' })
}

export function sendConversationMessage(
  id: string,
  message: string,
  confirm?: { tool: string; args: Record<string, unknown> },
  signal?: AbortSignal,
): Promise<AssistantResult> {
  return request(`/api/conversations/${id}/messages`, { method: 'POST', body: JSON.stringify({ message, confirm }) }, signal)
}

export interface ConversationStreamEvent {
  type: string
  conv_id?: string
  content?: string
  pending?: { tool: string; args: Record<string, unknown> } | null
  message?: string
  seq?: number
  data?: Record<string, unknown>
}

export async function startConversationStream(
  id: string,
  message: string,
  confirm?: { tool: string; args: Record<string, unknown> },
  signal?: AbortSignal,
): Promise<{ job_id: string }> {
  return request(`/api/conversations/${id}/messages/stream`, { method: 'POST', body: JSON.stringify({ message, confirm }) }, signal)
}

export function subscribeConversationEvents(
  id: string,
  jobId: string,
  onEvent: (event: ConversationStreamEvent) => void,
  signal?: AbortSignal,
): Promise<{ content: string; pending: { tool: string; args: Record<string, unknown> } | null }> {
  return new Promise((resolve, reject) => {
    const controller = new AbortController()
    const abort = () => controller.abort()
    if (signal?.aborted) {
      reject(new Error(t('apie.cancelled')))
      return
    }
    signal?.addEventListener('abort', abort)
    fetch(`/api/conversations/${id}/messages/stream/${jobId}/events`, { headers: { Accept: 'text/event-stream', ...authHeaders() }, signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
        const reader = res.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let finalContent = ''
        let finalPending: { tool: string; args: Record<string, unknown> } | null = null
        let streamError: Error | null = null
        let completed = false

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          let index
          while ((index = buffer.indexOf('\n\n')) !== -1) {
            const chunk = buffer.slice(0, index)
            buffer = buffer.slice(index + 2)
            for (const line of chunk.split('\n')) {
              if (!line.startsWith('data:')) continue
              const raw = line.slice(5).trim()
              if (!raw) continue
              const event = JSON.parse(raw) as ConversationStreamEvent
              onEvent(event)
              if (event.type === 'message_complete') {
                finalContent = event.content ?? ''
                finalPending = event.pending ?? null
                completed = true
                break
              }
              if (event.type === 'error') {
                streamError = new Error(event.message ?? t('apie.chatFailed'))
                break
              }
            }
            if (completed || streamError) break
          }
          if (completed || streamError) break
        }
        controller.abort()
        if (streamError) reject(streamError)
        else resolve({ content: finalContent, pending: finalPending })
      })
      .catch((err) => {
        if (err?.name === 'AbortError' || signal?.aborted) reject(new Error(t('apie.cancelled')))
        else reject(err)
      })
      .finally(() => signal?.removeEventListener('abort', abort))
  })
}

export function listTools(): Promise<{ tools: Tool[] }> {
  return request('/api/tools')
}

export function listSkills(): Promise<{ skills: Skill[] }> {
  return request('/api/skills')
}

export function createSkill(skill: Skill): Promise<{ name: string }> {
  return request('/api/skills', { method: 'POST', body: JSON.stringify(skill) })
}

export function updateSkill(name: string, skill: Skill): Promise<{ name: string }> {
  return request(`/api/skills/${name}`, { method: 'PUT', body: JSON.stringify(skill) })
}

export function deleteSkill(name: string): Promise<{ deleted: string }> {
  return request(`/api/skills/${name}`, { method: 'DELETE' })
}

export function getSettings(): Promise<Settings> {
  return request('/api/settings')
}

export function putSettings(settings: Partial<Settings>): Promise<Settings> {
  return request<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(settings) }).then((result) => {
    window.dispatchEvent(new Event('lattice:settings-changed'))
    return result
  })
}

export function getScope(): Promise<ScopePolicy> {
  return request('/api/scope')
}

export function putScope(policy: ScopePolicy): Promise<ScopePolicy> {
  return request('/api/scope', { method: 'PUT', body: JSON.stringify(policy) })
}

export function getSecuritySettings(): Promise<DangerPolicy> {
  return request('/api/settings/security')
}

export function putSecuritySettings(policy: DangerPolicy): Promise<DangerPolicy> {
  return request('/api/settings/security', { method: 'PUT', body: JSON.stringify(policy) })
}

export function listApprovals(): Promise<{ approvals: ApprovalDecision[] }> {
  return request('/api/approvals')
}

export function previewAssetImport(source: string): Promise<ImportPreview> {
  return request('/api/tools/import-asset', { method: 'POST', body: JSON.stringify({ source }) })
}

export function applyAssetImport(payload: { template_id: string; preview: ImportPreview; accepted_assets: ImportPreview['assets']; bindings: { tool: string; stage_id: string }[] }): Promise<{ skills: string[]; tools: string[]; bindings: { tool: string; stage_id: string }[] }> {
  return request('/api/tools/import-asset/apply', { method: 'POST', body: JSON.stringify(payload) })
}

export function preflightRun(template: Template, target: string): Promise<{ items: DangerPreflightItem[]; scope?: ScopePreflight; missing_tools?: MissingTool[] }> {
  return request('/api/run/preflight', { method: 'POST', body: JSON.stringify({ template, target }) })
}

export function exportReport(runId: string, format: ReportFormat): Promise<string> {
  return fetch(`/api/reports/${encodeURIComponent(runId)}?format=${format}`, { headers: authHeaders() }).then(async (res) => {
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
    return res.text()
  })
}

export function listProviders(): Promise<{ providers: Record<string, ProviderMeta> }> {
  return request('/api/providers')
}

export function listModels(params?: { base_url?: string; api_key?: string }): Promise<ModelList> {
  if (!params || (!params.base_url && !params.api_key)) return request('/api/models')
  const q = new URLSearchParams()
  if (params.base_url) q.set('base_url', params.base_url)
  if (params.api_key) q.set('api_key', params.api_key)
  return request(`/api/models?${q.toString()}`)
}

export function testProvider(settings: { base_url: string; api_key: string; model: string }): Promise<{ ok: boolean }> {
  return request('/api/settings/test', { method: 'POST', body: JSON.stringify(settings) })
}

export function getPreferences(): Promise<Preferences> {
  return request('/api/preferences')
}

export function putPreferences(patch: Partial<Preferences>): Promise<Preferences> {
  return request('/api/preferences', { method: 'PUT', body: JSON.stringify(patch) })
}

export function listToolchain(): Promise<{ tools: ToolchainInfo[] }> {
  return request('/api/toolchain')
}

export function listToolchainRegistry(): Promise<{ registry: ToolchainRegistryEntry[] }> {
  return request('/api/toolchain/registry')
}

export function installToolchain(tools: string[]): Promise<{ job_id: string; status: string }> {
  return request('/api/toolchain/install', { method: 'POST', body: JSON.stringify({ tools }) })
}

export function getToolchainInstallStatus(jobId: string): Promise<{
  job_id: string
  status: string
  error: string | null
  results: { name: string; status: string; detail?: string; version?: string | null }[]
  tools_installed: Record<string, boolean>
}> {
  return request(`/api/toolchain/install/${jobId}`)
}

export function listRuns(sessionId?: string): Promise<{ runs: RunSummary[] }> {
  const url = sessionId ? `/api/runs?session_id=${encodeURIComponent(sessionId)}` : '/api/runs'
  return request(url)
}

export function getRun(id: string): Promise<RunDetail> {
  return request(`/api/runs/${id}`)
}

export function listAssets(params: { kind?: string; q?: string; run_id?: string; session_id?: string } = {}): Promise<{ assets: Asset[] }> {
  const q = new URLSearchParams()
  if (params.kind) q.set('kind', params.kind)
  if (params.q) q.set('q', params.q)
  if (params.run_id) q.set('run_id', params.run_id)
  if (params.session_id) q.set('session_id', params.session_id)
  return request(`/api/assets?${q.toString()}`)
}

export function ingestAssets(runId: string): Promise<{ added: number; updated: number; relations: number }> {
  return request('/api/assets/ingest', { method: 'POST', body: JSON.stringify({ run_id: runId }) })
}

export function getAssetGraph(root = '', limit = 200, sessionId = ''): Promise<AssetGraph> {
  const q = new URLSearchParams()
  if (root) q.set('root', root)
  q.set('limit', String(limit))
  if (sessionId) q.set('session_id', sessionId)
  return request(`/api/assets/graph?${q.toString()}`)
}

export function replayRun(runId: string, after = 0, limit = 100): Promise<ReplayPage> {
  return request(`/api/runs/${encodeURIComponent(runId)}/replay?after=${after}&limit=${limit}`)
}

export function getWorkflowState(runId: string): Promise<RunWorkflowState> {
  return request(`/api/runs/${encodeURIComponent(runId)}/workflow-state`)
}

export function controlRun(runId: string, action: string, stageId?: string, confirm = false): Promise<Record<string, unknown>> {
  return request(`/api/runs/${encodeURIComponent(runId)}/control`, {
    method: 'POST',
    body: JSON.stringify({ action, stage_id: stageId, confirm }),
  })
}

export function getRunEvolution(runId: string): Promise<{ run_id: string; evolution: EvolutionReport }> {
  return request(`/api/runs/${encodeURIComponent(runId)}/evolution`)
}

export function refineTemplate(
  templateId: string,
  suggestions: EvolutionSuggestion[],
  runId?: string,
): Promise<{ new_version: number; applied: unknown[]; rejected: { suggestion: unknown; reason: string }[]; template: Template }> {
  return request(`/api/templates/${encodeURIComponent(templateId)}/refine`, {
    method: 'POST',
    body: JSON.stringify({ suggestions, run_id: runId }),
  })
}

export function getTemplateHistory(templateId: string): Promise<{ versions: number[] }> {
  return request(`/api/templates/${encodeURIComponent(templateId)}/history`)
}

export function rollbackTemplate(templateId: string, version: number): Promise<{ new_version: number; template: Template }> {
  return request(`/api/templates/${encodeURIComponent(templateId)}/rollback/${version}`, { method: 'POST' })
}

export function diffRuns(baseRunId: string, headRunId: string): Promise<RunDiff> {
  return request('/api/runs/diff', { method: 'POST', body: JSON.stringify({ base_run_id: baseRunId, head_run_id: headRunId }) })
}

export function listProjects(): Promise<{ projects: Project[]; current: string }> {
  return request('/api/projects')
}

export function getCurrentProject(): Promise<{ id: string; name: string; current_template_id: string; settings: Settings }> {
  return request('/api/projects/current')
}

export function createProject(name: string): Promise<{ id: string; name: string }> {
  return request('/api/projects', { method: 'POST', body: JSON.stringify({ name }) })
}

export function switchProject(id: string): Promise<{ current: string }> {
  return request('/api/projects/current', { method: 'PUT', body: JSON.stringify({ id }) })
}

export function renameProject(id: string, name: string): Promise<{ id: string; name: string }> {
  return request(`/api/projects/${id}/rename`, { method: 'POST', body: JSON.stringify({ name }) })
}

export function deleteProject(id: string): Promise<{ deleted: string }> {
  return request(`/api/projects/${id}`, { method: 'DELETE' })
}

export function saveRecipe(yaml: string): Promise<{ name: string }> {
  return request('/api/tools/recipes', { method: 'POST', body: JSON.stringify({ yaml }) })
}

export function deleteRecipe(name: string): Promise<{ deleted: string }> {
  return request(`/api/tools/recipes/${name}`, { method: 'DELETE' })
}

export function updateTool(name: string, tool: Tool): Promise<{ name: string }> {
  return request(`/api/tools/${name}`, { method: 'PUT', body: JSON.stringify(tool) })
}

export function runTool(tool: Tool, args: Record<string, unknown>): Promise<Record<string, unknown>> {
  return request('/api/tools/run', { method: 'POST', body: JSON.stringify({ tool, args }) })
}

export interface McpImportResult {
  tools: Tool[]
}

export interface ApprovalResult {
  approval_id: string
  tool: string
  args: Record<string, unknown>
}

export interface TryExecuteResult {
  tool: string
  result: Record<string, unknown>
  evidence?: string
  findings?: Finding[]
  report?: string | null
}

export function inspectImport(content: string, source = ''): Promise<ImportInspectResult> {
  return request('/api/import/inspect', { method: 'POST', body: JSON.stringify({ source, content }) })
}

export function confirmImport(payload: { draft_id?: string; draft?: Tool; fills?: ImportConfirmFills }): Promise<{ name: string; tool: Tool }> {
  return request('/api/import/confirm', { method: 'POST', body: JSON.stringify(payload) })
}

export function generateOutputSchema(tool: Tool, sample: string): Promise<{ output: Record<string, unknown> }> {
  return request('/api/import/output-schema', { method: 'POST', body: JSON.stringify({ tool, sample }) })
}

export function importMcp(source: string): Promise<McpImportResult> {
  return request('/api/tools/import-mcp', { method: 'POST', body: JSON.stringify({ source }) })
}

export function importSource(source: string): Promise<McpImportResult> {
  return request('/api/tools/import-source', { method: 'POST', body: JSON.stringify({ source }) })
}

export function saveImportedTool(tool: Tool): Promise<{ name: string }> {
  return request('/api/tools/imported', { method: 'POST', body: JSON.stringify({ tool }) })
}

export function tryImportedTool(tool: Tool, target: string): Promise<ApprovalResult> {
  return request('/api/tools/try', { method: 'POST', body: JSON.stringify({ tool, target }) })
}

export function executeImportedTool(approvalId: string): Promise<TryExecuteResult> {
  return request('/api/tools/try/execute', { method: 'POST', body: JSON.stringify({ approval_id: approvalId }) })
}

export function bindImportedTool(name: string, templateId: string, stageId?: string): Promise<{ template_id: string; tool: string }> {
  return request(`/api/tools/${encodeURIComponent(name)}/bind`, { method: 'POST', body: JSON.stringify({ template_id: templateId, stage_id: stageId }) })
}

export interface MarketplaceModule {
  id: string
  name: string
  name_i18n?: { zh: string; en: string }
  description: string
  description_i18n?: { zh: string; en: string }
  needs_tools: string[]
  tools_installed: Record<string, boolean>
  dependencies?: { secrets: string[]; runners: string[]; approvals: string[] }
}

export interface InstallModuleResult {
  id: string
  name: string
  job_id: string
  status: string
}

export function listMarketplace(): Promise<{ templates: MarketplaceModule[] }> {
  return request('/api/marketplace')
}

export function installMarketplace(id: string): Promise<InstallModuleResult> {
  return request(`/api/marketplace/${id}/install`, { method: 'POST' })
}

export function installStatus(jobId: string): Promise<{
  job_id: string
  status: string
  error: string | null
  tools_installed: Record<string, boolean>
  results: { name: string; status: string; detail: string }[]
}> {
  return request(`/api/marketplace/install/${jobId}`)
}

export function importTool(description: string): Promise<{ yaml: string }> {
  return request('/api/tools/import', { method: 'POST', body: JSON.stringify({ description }) })
}

export function reviewWorkflow(template: Template): Promise<{ issues: { severity: string; where: string; message: string }[] }> {
  return request('/api/workflow/review', { method: 'POST', body: JSON.stringify({ template }) })
}

export function understandWorkflow(template: Template): Promise<{ template: Template; issues: { severity: string; where: string; message: string }[] }> {
  return request('/api/workflow/understand', { method: 'POST', body: JSON.stringify({ template }) })
}

export function previewSuggestion(template: Template, suggestion: Record<string, unknown>): Promise<{ template: Template }> {
  return request('/api/templates/preview-suggestion', { method: 'POST', body: JSON.stringify({ template, suggestion }) })
}

export interface EvolutionRunSummary {
  run_id: string
  created_at: string
  target: string
  summary: string
  suggestion_count: number
}

export function listEvolutionRuns(templateId: string, limit = 10): Promise<{ runs: EvolutionRunSummary[] }> {
  return request(`/api/templates/${encodeURIComponent(templateId)}/evolution-runs?limit=${limit}`)
}

export interface TemplateVersionInfo {
  version: number
  lineage: { source: string; ref_id: string }
  saved_at: string
  current: boolean
}

export function listTemplateVersions(templateId: string, offset = 0, limit = 50): Promise<{ total: number; offset: number; limit: number; versions: TemplateVersionInfo[] }> {
  return request(`/api/templates/${encodeURIComponent(templateId)}/versions?offset=${offset}&limit=${limit}`)
}

export function getTemplateVersion(templateId: string, version: number): Promise<{ version: number; lineage: TemplateVersionInfo['lineage']; template: Template }> {
  return request(`/api/templates/${encodeURIComponent(templateId)}/versions/${version}`)
}

export function restoreTemplateVersion(templateId: string, version: number): Promise<{ new_version: number }> {
  return request(`/api/templates/${encodeURIComponent(templateId)}/versions/${version}/restore`, { method: 'POST' })
}

export function applyWorkflowSuggestion(templateId: string, suggestion: Record<string, unknown>): Promise<{ template_id: string; new_version?: number; stages: string[] }> {
  return request('/api/workflow/apply-suggestion', { method: 'POST', body: JSON.stringify({ template_id: templateId, suggestion }) })
}

export function listEvidence(sessionId?: string): Promise<{ evidence: Evidence[] }> {
  const url = sessionId ? `/api/evidence?session_id=${encodeURIComponent(sessionId)}` : '/api/evidence'
  return request(url)
}

export function getEvidence(id: string): Promise<Evidence> {
  return request(`/api/evidence/${id}`)
}

export function listFindings(sessionId?: string): Promise<{ findings: Finding[] }> {
  const url = sessionId ? `/api/findings?session_id=${encodeURIComponent(sessionId)}` : '/api/findings'
  return request(url)
}

export function getFinding(id: string): Promise<Finding> {
  return request(`/api/findings/${id}`)
}

export function stopRun(runId: string): Promise<{ stopped: string }> {
  return request(`/api/runs/${encodeURIComponent(runId)}/stop`, { method: 'POST' })
}

export function updateFindingStatus(id: string, status: 'confirmed' | 'pending' | 'false_positive' | 'needs_review'): Promise<Finding> {
  return request(`/api/findings/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) })
}

export function listLogs(): Promise<{ logs: LogLine[] }> {
  return request('/api/logs')
}

export function getDashboard(sessionId = '', days = 7): Promise<DashboardData> {
  const params = new URLSearchParams({ session_id: sessionId, days: String(days) })
  return request(`/api/dashboard?${params.toString()}`)
}

export interface AssetGroup {
  id: string
  name: string
  members: string[]
}

export interface GroupsPayload {
  tool_groups: AssetGroup[]
  skill_groups: AssetGroup[]
}

export function listGroups(): Promise<GroupsPayload> {
  return request('/api/groups')
}

export function generateTemplate(payload: { source?: string; mode?: string; description?: string; name?: string }): Promise<{ job_id: string }> {
  return request('/api/templates/generate', { method: 'POST', body: JSON.stringify(payload) })
}

export function subscribeGenerateEvents(
  jobId: string,
  onEvent: (event: { type: string; message?: string; template?: Template; report?: GenerationReport }) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const controller = new AbortController()
    const abort = () => controller.abort()
    if (signal?.aborted) {
      reject(new Error(t('apie.cancelled')))
      return
    }
    signal?.addEventListener('abort', abort)
    fetch(`/api/templates/generate/${jobId}/events`, { headers: { Accept: 'text/event-stream', ...authHeaders() }, signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
        const reader = res.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          let index
          while ((index = buffer.indexOf('\n\n')) !== -1) {
            const chunk = buffer.slice(0, index)
            buffer = buffer.slice(index + 2)
            for (const line of chunk.split('\n')) {
              if (!line.startsWith('data:')) continue
              const raw = line.slice(5).trim()
              if (!raw) continue
              const event = JSON.parse(raw)
              onEvent(event)
              if (event.type === 'complete' || event.type === 'error') {
                controller.abort()
                resolve()
                return
              }
            }
          }
        }
        controller.abort()
        resolve()
      })
      .catch((err) => {
        if (err?.name === 'AbortError' || signal?.aborted) reject(new Error(t('apie.cancelled')))
        else reject(err)
      })
      .finally(() => signal?.removeEventListener('abort', abort))
  })
}

export function createGroup(kind: 'tool' | 'skill', name: string): Promise<AssetGroup> {
  return request('/api/groups', { method: 'POST', body: JSON.stringify({ kind, name }) })
}

export function renameGroup(kind: 'tool' | 'skill', id: string, name: string): Promise<AssetGroup> {
  return request(`/api/groups/${id}`, { method: 'PUT', body: JSON.stringify({ kind, name }) })
}

export function deleteGroup(kind: 'tool' | 'skill', id: string): Promise<{ deleted: string }> {
  return request(`/api/groups/${id}?kind=${kind}`, { method: 'DELETE' })
}

export function setGroupMembers(kind: 'tool' | 'skill', id: string, members: string[]): Promise<AssetGroup> {
  return request(`/api/groups/${id}/members`, { method: 'PUT', body: JSON.stringify({ kind, members }) })
}

export interface TrashItem {
  kind: 'templates' | 'tools' | 'skills' | 'projects' | 'conversations'
  /** Restore/purge key; for conversations this is the conv id. */
  name: string
  /** Human label when it differs from `name` (conversations carry their title here). */
  display_name?: string
  filename?: string
  deleted_at?: string
}

export function listTrash(): Promise<{ items: TrashItem[] }> {
  return request('/api/trash')
}

export function restoreTrash(kind: TrashItem['kind'], name: string): Promise<{ restored: string; kind: string }> {
  return request(`/api/trash/${kind}/${encodeURIComponent(name)}/restore`, { method: 'POST' })
}

export function purgeTrash(kind: TrashItem['kind'], name: string): Promise<{ purged: string; kind: string }> {
  return request(`/api/trash/${kind}/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

export function emptyTrash(kind?: TrashItem['kind']): Promise<{ cleared: string }> {
  const url = kind ? `/api/trash?kind=${encodeURIComponent(kind)}` : '/api/trash'
  return request(url, { method: 'DELETE' })
}

export function resolveApproval(approvalId: string, approved: boolean, reason = ''): Promise<{ id: string; status: string; reason: string }> {
  return request(`/api/approvals/${encodeURIComponent(approvalId)}/resolve`, { method: 'POST', body: JSON.stringify({ approved, reason }) })
}

// ===== executions (M3-A) =====

export interface StageExecutionRow {
  run_id: string
  stage_id: string
  status: 'running' | 'completed' | 'failed' | 'skipped'
  started_at: string
  finished_at: string
  elapsed_ms: number
  tool_calls: number
  llm_calls: number
  tokens_in: number
  tokens_out: number
  error: string
}

export function getRunExecutions(runId: string): Promise<{ run_id: string; executions: StageExecutionRow[] }> {
  return request(`/api/runs/${encodeURIComponent(runId)}/executions`)
}
