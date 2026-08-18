import { Background, ReactFlow, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo } from 'react'

import topology from '@/data/graph_topology.json'
import { layoutTopology } from '@/lib/graphLayout'
import { cn } from '@/lib/utils'

interface GraphPanelProps {
  agentRoute: string[]
  degradedAgents: string[]
  /**
   * Barrido indeterminado en vez de coloreo por estado — para el caso en
   * que todavía no hay `agent_route` porque el grafo sigue corriendo
   * (Home, mientras un escenario en vivo está en `ANALYZING`). No indica
   * progreso real: W2 no deja nada leíble hasta que termina (§7.3).
   */
  animating?: boolean
}

type NodeStatus = 'ran' | 'degraded' | 'not-run' | 'synthetic'

// El nodo persistidor no figura en `agent_route` a propósito (contrato
// §2.5): "que corrió lo prueba la existencia de la fila". Este panel sólo
// se monta cuando `decision` existe, así que esa fila ya existe.
const SIEMPRE_CORRIO = new Set(['persist_decision'])

const STATUS_CLASSES: Record<NodeStatus, string> = {
  ran: 'border-primary bg-secondary text-secondary-foreground',
  degraded: 'border-destructive bg-destructive/10 text-destructive',
  'not-run': 'border-dashed border-border bg-muted text-muted-foreground',
  synthetic: 'border-border bg-background text-muted-foreground text-xs',
}

function estadoDe(nodeId: string, synthetic: boolean, ran: Set<string>, degraded: Set<string>): NodeStatus {
  if (synthetic) return 'synthetic'
  if (degraded.has(nodeId)) return 'degraded'
  if (ran.has(nodeId) || SIEMPRE_CORRIO.has(nodeId)) return 'ran'
  return 'not-run'
}

export function GraphPanel({ agentRoute, degradedAgents, animating = false }: GraphPanelProps) {
  const { nodes, edges } = useMemo(() => {
    const base = layoutTopology(topology)
    const ran = new Set(agentRoute)
    const degraded = new Set(degradedAgents)
    const synthById = new Map(topology.nodes.map((n) => [n.id, n.synthetic]))

    const nodes: Node[] = base.nodes.map((n) => {
      if (animating) {
        const level = (n.data as { level?: number }).level ?? 0
        return {
          ...n,
          className: cn(
            'rounded-md border px-3 py-2 text-center text-sm font-medium',
            'border-primary bg-secondary text-secondary-foreground',
          ),
          style: {
            ...n.style,
            animation: 'node-pulse 1.8s ease-in-out infinite',
            animationDelay: `${level * 0.3}s`,
          },
        }
      }
      const status = estadoDe(n.id, synthById.get(n.id) ?? false, ran, degraded)
      return {
        ...n,
        className: cn(
          'rounded-md border px-3 py-2 text-center text-sm font-medium',
          STATUS_CLASSES[status],
        ),
      }
    })

    return { nodes, edges: base.edges }
  }, [agentRoute, degradedAgents, animating])

  return (
    <div className="h-80 w-full rounded-md border">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
      </ReactFlow>
    </div>
  )
}
