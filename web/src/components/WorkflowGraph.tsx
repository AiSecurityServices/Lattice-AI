import dagre from '@dagrejs/dagre'
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { forwardRef, useEffect, useImperativeHandle } from 'react'
import { t, useLang } from '../i18n'
import type { RunWorkflowState, StageStatus, Template } from '../types'

export interface DepEdge {
  id: string
  source: string
  target: string
  condition?: Record<string, unknown> | null
}

export interface WorkflowGraphHandle {
  /** Pan/zoom the canvas so the stage node is centered (event-log linkage). */
  focusStage: (stageId: string) => void
}

export function deriveEdges(template: Template): DepEdge[] {
  const out: DepEdge[] = []
  for (const s of template.stages) {
    for (const dep of s.depends_on ?? []) {
      out.push({ id: `dep-${dep}-${s.id}`, source: dep, target: s.id, condition: s.condition ?? null })
    }
  }
  return out
}

export function conditionText(c: Record<string, unknown> | null | undefined): string {
  if (!c) return ''
  const op = String(c.op ?? '')
  if (op === 'truthy') return t('wf.cond.truthy').replace('{key}', String(c.key))
  if (op === 'equals') return `${c.key} = ${JSON.stringify(c.value)}`
  if (op === 'in') return `${c.key} ∈ [${(c.values as unknown[] ?? []).join(', ')}]`
  if (op === 'not') return `${t('wf.cond.not')}(${conditionText(c.condition as any)})`
  if (op === 'and') return `${t('wf.cond.and')}(${(c.conditions as any[] ?? []).map(conditionText).join(' & ')})`
  if (op === 'or') return `${t('wf.cond.or')}(${(c.conditions as any[] ?? []).map(conditionText).join(' | ')})`
  return JSON.stringify(c)
}

export function statusOf(runtime: RunWorkflowState | null | undefined, stageId: string): StageStatus | 'idle' {
  return runtime?.stage_status?.[stageId] ?? 'idle'
}

export function layoutNodes(template: Template): Record<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph()
  // dagre keeps parallel depends_on branches side by side; tighter separations
  // just compact the same DAG so fitView needs less shrinkage.
  g.setGraph({ rankdir: 'LR', nodesep: 50, ranksep: 100 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const s of template.stages) g.setNode(s.id, { width: 220, height: 72 })
  for (const e of deriveEdges(template)) g.setEdge(e.source, e.target)
  dagre.layout(g)
  const out: Record<string, { x: number; y: number }> = {}
  for (const s of template.stages) {
    const n = g.node(s.id)
    out[s.id] = { x: n.x - 110, y: n.y - 36 }
  }
  return out
}

interface StageData extends Record<string, unknown> {
  name: string
  status: StageStatus | 'idle'
  optional: boolean
  hasCondition: boolean
  highlighted: boolean
}

type StageNode = Node<StageData>

const nodeTypes = { stage: StageCard }

function StageCard({ data, selected }: NodeProps<StageNode>) {
  useLang()
  const statusClass = data.status === 'idle' ? '' : ` wf-status-${data.status}`
  const stateClass = data.status === 'idle' ? '' : ` wf-st-${data.status}`
  return (
    <div className={`stage-node wf-node${selected ? ' selected' : ''}${data.optional ? ' wf-optional' : ''}${stateClass}${data.highlighted ? ' wf-highlight' : ''}`}>
      <Handle type="target" position={Position.Left} className="stage-node-handle" />
      <Handle type="target" position={Position.Top} id="in-top" className="stage-node-handle" />
      <Handle type="target" position={Position.Bottom} id="in-bottom" className="stage-node-handle" />
      <div className="stage-node-title">{data.name}</div>
      <div className="wf-node-meta">
        {data.hasCondition && <span className="wf-chip">{t('wf.chip.condition')}</span>}
        {data.optional && <span className="wf-chip">{t('wf.chip.optional')}</span>}
        {data.status !== 'idle' && <span className={`wf-badge${statusClass}`}>{data.status}</span>}
      </div>
      <Handle type="source" position={Position.Right} className="stage-node-handle" />
    </div>
  )
}

interface WorkflowGraphProps {
  template: Template
  runtime?: RunWorkflowState | null
  selectedNodeId?: string | null
  selectedEdgeId?: string | null
  highlightStageId?: string | null
  onNodeClick?: (id: string) => void
  onEdgeClick?: (id: string) => void
  onNodeContextMenu?: (id: string, event: React.MouseEvent) => void
}

function GraphBody({ template, runtime, selectedNodeId, selectedEdgeId, highlightStageId, onNodeClick, onEdgeClick, onNodeContextMenu }: WorkflowGraphProps) {
  useLang()
  const positions = layoutNodes(template)
  const nodes: StageNode[] = template.stages.map((s) => ({
    id: s.id,
    type: 'stage',
    position: positions[s.id] ?? { x: 0, y: 0 },
    selected: selectedNodeId === s.id,
    data: {
      name: s.name,
      status: statusOf(runtime, s.id),
      optional: s.optional ?? false,
      hasCondition: !!s.condition,
      highlighted: highlightStageId === s.id,
    },
  }))

  const edges: Edge[] = deriveEdges(template).map((e) => {
    const sourceIdx = template.stages.findIndex((s) => s.id === e.source)
    const targetIdx = template.stages.findIndex((s) => s.id === e.target)
    const isBack = targetIdx <= sourceIdx
    const stroke = e.condition ? '#1F6C9F' : isBack ? '#D97706' : '#8C8C87'
    const style: Record<string, string | number> = { stroke }
    if (isBack) style.strokeDasharray = '6 4'
    if (selectedEdgeId === e.id) style.strokeWidth = 3
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.condition ? conditionText(e.condition) : undefined,
      labelStyle: { fill: 'var(--text-muted)', fontSize: 11, fontWeight: 500 },
      labelBgStyle: { fill: 'var(--surface)', stroke: 'var(--border)', strokeWidth: 1 },
      labelBgPadding: [4, 2] as [number, number],
      labelBgBorderRadius: 4,
      markerEnd: { type: MarkerType.ArrowClosed, width: 24, height: 24, color: stroke },
      style,
    }
  })

  return (
    <div className="wf-graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        nodesConnectable={false}
        fitView
        minZoom={0.5}
        maxZoom={1.8}
        fitViewOptions={{ padding: 0.2, maxZoom: 1.8, minZoom: 0.5 }}
        onNodeClick={(_, n) => onNodeClick?.(n.id)}
        onEdgeClick={(_, e) => onEdgeClick?.(e.id)}
        onNodeContextMenu={(event, n) => {
          event.preventDefault()
          onNodeContextMenu?.(n.id, event)
        }}
      >
        <Background gap={16} color="var(--border)" />
        <Controls />
        <MiniMap pannable={false} zoomable={false} className="designer-minimap" />
      </ReactFlow>
    </div>
  )
}

function GraphWithApi({ handleRef, template, ...props }: WorkflowGraphProps & { handleRef: React.Ref<WorkflowGraphHandle> }) {
  const instance = useReactFlow()
  // Readable first paint: fit the whole graph, but if that costs too much
  // zoom (stage labels shrink to ~7px on long chains), anchor on the entry
  // stage at a readable zoom instead — panning explores the rest and the
  // MiniMap keeps orientation.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void instance
        .fitView({ padding: 0.15, maxZoom: 1.2, duration: 0 })
        .then(() => {
          if (instance.getZoom() >= 0.8) return
          const first = template.stages[0]
          if (!first) return
          return instance.fitView({ nodes: [{ id: first.id }], maxZoom: 0.8, padding: 0.8, duration: 0 })
        })
        .catch(() => {})
    }, 80)
    return () => window.clearTimeout(timer)
  }, [instance, template])
  useImperativeHandle(handleRef, () => ({
    focusStage: (stageId: string) => {
      const node = instance.getNode(stageId)
      if (!node) return
      const width = (node.measured?.width ?? node.style?.width ?? 220) as number
      const height = (node.measured?.height ?? node.style?.height ?? 72) as number
      instance.setCenter(node.position.x + width / 2, node.position.y + height / 2, {
        zoom: 1.2,
        duration: 400,
      })
    },
  }))
  return <GraphBody template={template} {...props} />
}

const WorkflowGraph = forwardRef<WorkflowGraphHandle, WorkflowGraphProps>(function WorkflowGraph(props, ref) {
  return (
    <ReactFlowProvider>
      <GraphWithApi {...props} handleRef={ref} />
    </ReactFlowProvider>
  )
})

export default WorkflowGraph
