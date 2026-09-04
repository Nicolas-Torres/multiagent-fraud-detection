import { Background, ReactFlow, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { type CSSProperties, useMemo } from 'react'

import topology from '@/data/graph_topology.json'
import { layoutTopology } from '@/lib/graphLayout'

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
  /**
   * `false` sólo para el progreso en vivo (ADR-0018): ahí `persist_decision`
   * tiene que esperar su propio evento SSE como cualquier otro nodo, en vez
   * de darse por corrido de entrada -si no, aparece iluminado desde el
   * primer instante, antes de que el árbitro siquiera haya decidido-, y
   * habilita el estado "en curso" (ver `estadoDe`): no tiene sentido para
   * un caso ya resuelto, donde no queda nada por empezar.
   */
  caseDecided?: boolean
}

type NodeStatus = 'ran' | 'en-progreso' | 'degraded' | 'not-run' | 'synthetic'

// El nodo persistidor no figura en `agent_route` a propósito (contrato
// §2.5): "que corrió lo prueba la existencia de la fila" — válido sólo
// una vez que la fila existe (`caseDecided`), nunca durante el streaming
// en vivo de un caso que todavía está corriendo.
const SIEMPRE_CORRIO = new Set(['persist_decision'])

// El stream de ADR-0018 sólo avisa "este nodo terminó", nunca "este nodo
// empezó" — así que dos nodos que el grafo corre en paralelo de verdad
// (`evidence_aggregation` alimenta tanto a `debate_pro_customer` como a
// `debate_pro_fraud` en el mismo superstep) se ven como secuenciales en
// vivo, porque cada llamada a un LLM tarda lo que tarda. Para no mentir
// al revés -mostrar como "sin empezar" algo que sí está corriendo-, se
// infiere "en curso" desde la topología: un nodo está en curso si todos
// sus predecesores ya corrieron pero él todavía no.
const PREDECESORES = new Map<string, string[]>()
for (const arista of topology.edges) {
  const lista = PREDECESORES.get(arista.target) ?? []
  lista.push(arista.source)
  PREDECESORES.set(arista.target, lista)
}

// El propio CSS de React Flow (`.react-flow__node-default`) fija `border`,
// `background-color`, `border-radius`, `padding` y `font-size` -todo lo
// visual- con la misma especificidad que una utilidad de Tailwind (una
// sola clase), y como su hoja se inyecta después, gana el empate y pisa
// por completo cualquier clase de Tailwind para esas propiedades: la clase
// queda en el DOM, pero no hace nada, sin error ni advertencia. Por eso
// todo esto va como estilo inline -lo único con prioridad garantizada
// frente a una hoja de terceros sin tocar `!important`.
const BASE: CSSProperties = {
  padding: '8px 12px',
  borderRadius: '6px',
  fontSize: '0.875rem',
  fontWeight: 500,
  textAlign: 'center',
}

interface EstiloNodo extends CSSProperties {
  border: string
  backgroundColor: string
  color: string
}

const ESTILOS: Record<NodeStatus, EstiloNodo> = {
  ran: { border: '2px solid #10b981', backgroundColor: '#ecfdf5', color: '#065f46' },
  'en-progreso': {
    border: '2px solid #f59e0b',
    backgroundColor: '#fffbeb',
    color: '#78350f',
    animation: 'node-pulse 1.4s ease-in-out infinite',
  },
  degraded: {
    border: '1px solid var(--destructive)',
    backgroundColor: 'color-mix(in oklch, var(--destructive) 10%, transparent)',
    color: 'var(--destructive)',
  },
  'not-run': { border: '1px dashed var(--border)', backgroundColor: 'var(--muted)', color: 'var(--muted-foreground)' },
  // Fijo, no `var(--border)`/`var(--background)`: esos dos coinciden por
  // definición con el fondo del lienzo (mismo token), así que START/END
  // quedaban sin ningún contraste de relleno, en modo claro y en oscuro por
  // igual. Índigo en vez de gris para no competir con la semántica de
  // estado (emerald/amber/rojo) ni confundirse con el gris punteado de
  // `not-run`.
  synthetic: {
    border: '1px solid #6366f1',
    backgroundColor: '#eef2ff',
    color: '#3730a3',
    fontSize: '0.75rem',
  },
}

function estadoDe(
  nodeId: string,
  synthetic: boolean,
  ran: Set<string>,
  degraded: Set<string>,
  caseDecided: boolean,
): NodeStatus {
  if (synthetic) return 'synthetic'
  if (degraded.has(nodeId)) return 'degraded'
  if (ran.has(nodeId) || (caseDecided && SIEMPRE_CORRIO.has(nodeId))) return 'ran'
  if (!caseDecided) {
    const previos = PREDECESORES.get(nodeId) ?? []
    const listo = previos.length > 0 && previos.every((p) => p === '__start__' || ran.has(p))
    if (listo) return 'en-progreso'
  }
  return 'not-run'
}

export function GraphPanel({
  agentRoute,
  degradedAgents,
  animating = false,
  caseDecided = true,
}: GraphPanelProps) {
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
          style: {
            ...n.style,
            ...BASE,
            ...ESTILOS.ran,
            animation: 'node-pulse 1.8s ease-in-out infinite',
            animationDelay: `${level * 0.3}s`,
          },
        }
      }
      const status = estadoDe(n.id, synthById.get(n.id) ?? false, ran, degraded, caseDecided)
      return {
        ...n,
        className: 'transition-colors duration-500',
        style: { ...n.style, ...BASE, ...ESTILOS[status] },
      }
    })

    return { nodes, edges: base.edges }
  }, [agentRoute, degradedAgents, animating, caseDecided])

  return (
    <div className="h-80 w-full rounded-md border">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
      </ReactFlow>
    </div>
  )
}
