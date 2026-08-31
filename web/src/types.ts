export interface ToolBinding {
  tool: string
  key?: string | null
  condition?: Record<string, unknown> | null
  defaults?: Record<string, unknown>
  args_from?: Record<string, string>
  note?: string
  enabled?: boolean
}

export type AssetKind = 'domain' | 'subdomain' | 'ip' | 'port' | 'service' | 'technology' | 'endpoint'
export type AssetRelationKind = 'resolves_to' | 'has_port' | 'runs' | 'uses' | 'links_to'

export interface Asset {
  id: string
  kind: AssetKind
  value: string
  natural_key: string
  source_run_id?: string
  source_tool?: string
  evidence_ids?: string[]
  first_seen?: string
  last_seen?: string
}

export interface AssetRelation {
  id: string
  from_asset: string
  to_asset: string
  relation: AssetRelationKind
  evidence_ids?: string[]
  created_at?: string
}

export interface AssetGraph {
  nodes: Asset[]
  edges: AssetRelation[]
}

export interface ReplayPage {
  run_id: string
  events: SessionEvent[]
  next_after: number
  has_more: boolean
}

export interface RunDiff {
  base_run_id: string
  head_run_id: string
  findings: { added: Finding[]; removed: Finding[]; changed: { base: Finding; head: Finding }[] }
  assets: { added: Asset[]; removed: Asset[]; changed: { base: Asset; head: Asset }[] }
  evidence: { added: Evidence[]; removed: Evidence[]; changed: { base: Evidence; head: Evidence }[] }
}

export type StageStatus = 'pending' | 'ready' | 'running' | 'completed' | 'skipped' | 'failed'

export interface RunWorkflowState {
  run_id: string
  current_stage: string | null
  stage_status: Record<string, StageStatus>
  checkpoint_version?: number
}

export interface SkillBinding {
  skill: string
  enabled?: boolean
}

export interface Tool {
  name: string
  description?: string
  parameters?: Record<string, unknown>
  output?: Record<string, unknown>
  runner?: 'cli' | 'builtin' | 'adapter'
  command?: string[]
  scope?: string[]
  approval?: 'allow' | 'ask' | 'deny'
  secret_fields?: string[]
  builtin?: boolean
  available?: boolean
  status?: 'builtin' | 'cli' | 'adapter' | 'unavailable'
  capability?: 'recon' | 'vuln' | 'fuzz' | 'other'
  usage?: 'builtin' | 'cli' | 'mcp' | 'http_api' | 'adapter'
  version?: string | null
  tier_hint?: 'real' | 'sim' | 'unavailable'
  danger?: 'passive' | 'active' | 'aggressive'
  registry?: boolean
}

export interface Stage {
  id: string
  name: string
  goal?: string
  depends_on?: string[]
  optional?: boolean
  condition?: Record<string, unknown> | null
  gates?: { name: string; check: Record<string, unknown>; on_fail?: 'block' | 'warn' }[]
  tools?: ToolBinding[]
  skills?: SkillBinding[]
  completion?: Record<string, unknown> | null
  timeout?: number
}

export interface Template {
  id: string
  name: string
  start: string
  stages: Stage[]
  tools: Tool[]
  skills?: Skill[]
  summary?: string
  name_i18n?: { zh: string; en: string }
  description_i18n?: { zh: string; en: string }
  version?: number
}

export interface SessionEvent {
  seq: number
  type: string
  data: Record<string, unknown>
}

export interface RunResult {
  id: string
  facts: Record<string, unknown>
  events: SessionEvent[]
  report?: string | null
  evolution?: EvolutionReport
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatResult {
  run_id: string
  content: string
  facts: Record<string, unknown>
  events: SessionEvent[]
}

export interface AssistantResult {
  content: string
  events: SessionEvent[]
  pending?: { tool: string; args: Record<string, unknown> } | null
}

export interface Skill {
  name: string
  content?: string
  description?: string
  category?: string
  tags?: string[]
  source?: string
  classification?: { cve?: string; cwe?: string; cvss?: string; epss?: string; severity?: string }
}

  export interface Settings {
    provider: string
    base_url: string
    model: string
    api_key: string
    reasoning_effort?: string
    has_api_key?: boolean
  }

  export interface Preferences {
    theme: 'system' | 'light' | 'dark'
    language: 'zh' | 'en'
  }

  export interface ToolchainInfo {
    name: string
    available: boolean
    status: string
  }

export interface ScopePolicy {
  allow_domains: string[]
  allow_ips: string[]
  allow_cidrs: string[]
  allow_ports: number[]
  allow_url_prefixes: string[]
}

export interface ScopePreflight {
  configured: boolean
  ok: boolean
  reason: string
  restricted: boolean
}

export interface MissingTool {
  tool: string
  install_mode: 'auto' | 'manual' | 'none'
  hint: string
  has_fallback: boolean
}

export interface ToolchainRegistryEntry {
  name: string
  category: string
  output_format: string
  parse_level: string
  command: string[]
  install_primary: string
  install_manual: string
  version_cmd: string[]
  license: string
  builtin_fallback: string
  danger: 'passive' | 'active' | 'aggressive'
  platforms: Record<string, string>
  notes: string
  installed: boolean
  version: string | null
  install_mode: 'auto' | 'manual' | 'none'
}

export interface DangerWhitelistItem {
  id: string
  tool: string
  category: 'destructive' | 'data-exfil' | 'system-control'
  created_at?: string
}

export interface DangerPolicy {
  level: 'strict' | 'standard' | 'lenient'
  whitelist: DangerWhitelistItem[]
}

export interface ImportAsset {
  type: 'skill' | 'tool'
  name: string
  description?: string
  content?: string
  data?: Skill | Tool
  warnings?: string[]
}

export interface ImportPreview {
  source: string
  fingerprint: string
  assets: ImportAsset[]
  suggested_bindings: { tool: string; stage_id: string }[]
  warnings: string[]
}

export type ImportInspectStatus = 'completed' | 'completed_with_warnings' | 'pending' | 'failed'

export interface ImportInspectResult {
  status: ImportInspectStatus
  draft_id?: string | null
  draft?: Tool | null
  missing?: { secrets: string[]; tools: string[]; approvals: string[] }
  warnings?: string[]
  reason?: string
}

export interface ImportConfirmFills {
  secrets?: Record<string, string>
  name?: string
  category?: string
  description?: string
}

export interface ApprovalDecision {
  id: string
  run_id?: string
  tool: string
  args_redacted?: Record<string, unknown>
  hit_rules?: string[]
  status: 'allowed_once' | 'allowed_run' | 'whitelisted' | 'denied'
  chosen_action?: 'allow_once' | 'allow_run' | 'whitelist' | 'deny'
  reason?: string
  created_at?: string
}

export interface DangerPreflightItem {
  tool: string
  category: 'destructive' | 'data-exfil' | 'system-control'
  rule_id: string
  action: 'allow' | 'ask' | 'deny'
  reason: string
}

export type ReportFormat = 'md' | 'html' | 'json'

export interface RunSummary {
  id: string
  template_id: string
  target: string
  created_at?: string
  kind?: 'run' | 'chat'
  output?: string | null
}

export interface RunDetail extends RunSummary {
  facts: Record<string, unknown>
  events: SessionEvent[]
  report?: string | null
  evolution?: EvolutionReport
}

export interface Project {
  id: string
  name: string
}

export interface Evidence {
  id: string
  run_id: string
  stage_id: string
  tool: string
  args?: Record<string, unknown>
  result?: Record<string, unknown>
  created_at?: string
  hash?: string
}

export interface Finding {
  id: string
  run_id?: string
  title: string
  severity: string
  status: string
  cwe?: string
  cvss?: string
  target?: string
  confidence?: string
  evidence_ids?: string[]
  summary?: string
  impact?: string
  remediation?: string
  grounding?: { status?: string; detail?: string; matched_snippets?: string[] }
}

export interface LogLine {
  run_id: string
  seq?: number
  type?: string
  data?: Record<string, unknown>
  created_at?: string
}

export interface GenerationReport {
  source?: { type?: string; value?: string; depth?: string }
  understood?: { summary?: string; entrypoints?: string[]; capabilities?: string[]; dependencies?: string[] }
  imports?: {
    tools: { name: string; kind: string; status: string; detail?: string }[]
    skills: { name: string; status: string; detail?: string }[]
  }
  issues?: { severity: string; where: string; message: string; resolution?: string }[]
  confidence?: string
  notes?: string
}

export type SessionKind = 'assistant' | 'task'
export type Effort = 'off' | 'low' | 'medium' | 'high'

export interface ConversationMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface Session {
  id: string
  name: string
  kind: SessionKind
  template_id: string
  model: string
  reasoning_effort: string
  project_id: string
  created_at: string
  updated_at: string
  messages: ConversationMessage[]
  target: string
  autonomous: boolean
  self_check?: boolean
  last_run_id: string
}

export interface ProviderMeta {
  name: string
  base_url: string
  model: string
  reasoning?: { efforts: string[]; thinking?: boolean }
}

export interface SelfCheckNote {
  kind: 'difficulty' | 'conflict' | 'misunderstanding' | 'opportunity'
  text: string
}

export interface EvolutionStep {
  label: string
  difficulties?: string[]
  conflicts?: string[]
  misunderstandings?: string[]
}

export interface EvolutionSuggestion {
  type: string
  where?: string
  detail?: string
  stage_id?: string
  stage_name?: string
  tool_name?: string
  after_stage_id?: string
  depends_on?: string
  condition?: Record<string, unknown> | null
  optional?: boolean
  name?: string
  check?: Record<string, unknown>
  on_fail?: 'block' | 'warn'
}

export interface EvolutionReport {
  summary?: string
  steps?: EvolutionStep[]
  suggestions?: EvolutionSuggestion[]
  unresolved?: string[]
  confidence?: string
}

export interface ModelList {
  provider: string
  models: string[]
  efforts: string[]
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

export interface DashboardKpi {
  total: number
  severity?: Record<string, number>
  spark: number[]
}

export interface DashboardRunItem {
  id: string
  template_id: string
  target: string
  kind: string
  created_at: string
}

export interface DashboardFindingItem {
  id: string
  title: string
  severity: string
  status: string
  target: string
  run_id: string
  created_at: string
}

export interface DashboardData {
  session_id: string
  days: string[]
  kpis: {
    assets: DashboardKpi
    subdomains: DashboardKpi
    findings: DashboardKpi
    runs: DashboardKpi
  }
  recent_runs: DashboardRunItem[]
  recent_findings: DashboardFindingItem[]
}
