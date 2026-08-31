import { useLang, t } from '../i18n'
import type { AssetGraph as AssetGraphData } from '../types'

export function AssetGraph({ graph }: { graph: AssetGraphData }) {
  useLang()
  if (graph.nodes.length === 0) {
    return <div className="asset-graph-empty">{t('agraph.empty')}</div>
  }
  const positions = new Map<string, { x: number; y: number }>()
  graph.nodes.slice(0, 12).forEach((asset, index) => {
    const angle = (index / Math.min(12, graph.nodes.length)) * Math.PI * 2
    positions.set(asset.id, {
      x: 400 + Math.cos(angle) * 160,
      y: 120 + Math.sin(angle) * 70,
    })
  })
  return (
    <div className="asset-graph">
      <svg viewBox="0 0 800 240" role="img" aria-label="asset graph">
        {graph.edges.map((edge) => {
          const from = positions.get(edge.from_asset)
          const to = positions.get(edge.to_asset)
          if (!from || !to) return null
          return <line key={edge.id} x1={from.x} y1={from.y} x2={to.x} y2={to.y} className="asset-graph-edge" />
        })}
        {graph.nodes.slice(0, 12).map((asset) => {
          const pos = positions.get(asset.id)
          if (!pos) return null
          return (
            <g key={asset.id}>
              <circle cx={pos.x} cy={pos.y} r={34} className="asset-graph-node" />
              <text x={pos.x} y={pos.y + 4} textAnchor="middle" className="asset-graph-label">
                {asset.value.length > 16 ? `${asset.value.slice(0, 16)}…` : asset.value}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
