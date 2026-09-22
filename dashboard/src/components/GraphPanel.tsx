import { Background, ReactFlow, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { type CSSProperties, useMemo } from 'react'

import topology from '@/data/graph_topology.json'
import { useIsMobile } from '@/hooks/useIsMobile'
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

// Categoría por tipo de nodo -segundo eje, aparte del estado de ejecución
// (`ESTILOS`, abajo)-, comunicada sólo por los recuadros y sus etiquetas de
// texto: se probó primero una franja de color por nodo (`boxShadow`) y se
// descartó -no se leía bien-, así que acá no queda ningún estilo por nodo,
// sólo la decoración de grupo más abajo.
type Categoria = 'deterministico' | 'rag' | 'llm'

const COLOR_CATEGORIA: Record<Categoria, string> = {
  deterministico: '#eab308',
  rag: '#3b82f6',
  llm: '#f97316',
}

// Los recuadros de agrupación (los "recuadros" de la anotación a mano):
// sólo para clusters realmente contiguos en el layout -`evidence_aggregation`
// y `persist_decision` son deterministas también, pero no son vecinos de
// estos tres en el grafo real, así que sólo reciben una etiqueta suelta
// (`ETIQUETAS_SUELTAS`, abajo), nunca un recuadro que sugiera una
// adyacencia que no existe.
// `\n` entre el texto y el paréntesis -junto con `whiteSpace: 'pre-line'`
// en el estilo del nodo de etiqueta, más abajo- para que no compita por
// ancho con el recuadro que describe.
const GRUPOS: { key: string; label: string; nodeIds: string[]; color: string }[] = [
  {
    key: 'deterministico',
    label: 'Determinísticos\n(no LLM)',
    nodeIds: ['transaction_context', 'behavioral_pattern', 'external_threat_intel'],
    color: COLOR_CATEGORIA.deterministico,
  },
  {
    key: 'rag',
    label: 'Retrieval semántico\n(gemini-embedding-2)',
    nodeIds: ['internal_policy_rag'],
    color: COLOR_CATEGORIA.rag,
  },
  {
    key: 'llm',
    label: 'LLM Anthropic\n(claude-sonnet-5)',
    nodeIds: ['debate_pro_fraud', 'debate_pro_customer', 'decision_arbiter', 'explainability'],
    color: COLOR_CATEGORIA.llm,
  },
]

const ETIQUETAS_SUELTAS: { nodeId: string; label: string; color: string }[] = [
  { nodeId: 'evidence_aggregation', label: 'Scoring determinístico', color: COLOR_CATEGORIA.deterministico },
  { nodeId: 'persist_decision', label: 'Escritura en BD', color: COLOR_CATEGORIA.deterministico },
]

// Nominal, no medido: `layoutTopology` no fija una altura real (los nodos
// normales se ajustan a su contenido), así que el recuadro se calcula con
// una estimación generosa de ancho/alto de nodo — el padding de sobra
// (`GROUP_PADDING_*`) absorbe la diferencia sin que el recuadro quede
// corto. Horizontal más angosto que vertical a propósito: entre columnas
// vecinas sólo hay 30px de por sí (`COL_GAP` 200 − `NODE_WIDTH` 170), así
// que un padding de 20px de cada lado hacía que dos recuadros de columnas
// contiguas (determinísticos/RAG) se superpusieran 10px.
const NODE_WIDTH = 170
const NODE_HEIGHT = 40
const GROUP_PADDING_X = 10
const GROUP_PADDING_Y = 20
// Dos líneas (texto + paréntesis en la suya, ver `GRUPOS`), no una.
const GROUP_LABEL_HEIGHT = 36

interface BBox {
  x: number
  y: number
  width: number
  height: number
}

function bboxDeGrupo(nodos: Node[], ids: string[]): BBox {
  const miembros = nodos.filter((n) => ids.includes(n.id))
  const xs = miembros.map((n) => n.position.x)
  const ys = miembros.map((n) => n.position.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs) + NODE_WIDTH
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys) + NODE_HEIGHT
  return {
    x: minX - GROUP_PADDING_X,
    y: minY - GROUP_PADDING_Y - GROUP_LABEL_HEIGHT,
    width: maxX - minX + GROUP_PADDING_X * 2,
    height: maxY - minY + GROUP_PADDING_Y * 2 + GROUP_LABEL_HEIGHT,
  }
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

// Tipo de nodo propio para las etiquetas de recuadro y las sueltas -ni
// `default` (dibuja los dos `Handle`, los "puntos negros" que tapaban el
// texto) ni `group` (el componente real de React Flow, `GroupNode`, es
// literal `return null`: no renderiza `data.label` en absoluto, se
// probó y el texto desaparecía por completo) sirven acá. Este no
// renderiza ningún `Handle`, sólo el texto — la posición/tamaño los
// sigue aplicando React Flow por fuera, igual que a cualquier nodo.
function EtiquetaNode({ data }: NodeProps) {
  return (data as { label?: string })?.label ?? null
}

const NODE_TYPES = { etiqueta: EtiquetaNode }

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
  // Bajo el breakpoint, el layout pasa a vertical (`graphLayout.ts`): un
  // celular es angosto pero alto, así que apilar niveles aprovecha eso en
  // vez de encoger el layout horizontal hasta ilegible.
  const esMobile = useIsMobile()

  const { nodes, edges } = useMemo(() => {
    const base = layoutTopology(topology, esMobile ? 'vertical' : 'horizontal')
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

    // Recuadros de agrupación, calculados de las posiciones reales de sus
    // miembros -no coordenadas fijas a mano-, más su etiqueta de texto.
    // Van primero en el array (detrás, en z-order) y son puramente
    // decorativos: sin interacción, sin afectar `estadoDe`/`acentoDe`.
    const decoracion: Node[] = GRUPOS.flatMap((g) => {
      const box = bboxDeGrupo(base.nodes, g.nodeIds)
      const recuadro: Node = {
        id: `group-box-${g.key}`,
        type: 'group',
        position: { x: box.x, y: box.y },
        style: {
          width: box.width,
          height: box.height,
          border: `1.5px dashed ${g.color}`,
          backgroundColor: `color-mix(in oklch, ${g.color} 6%, transparent)`,
          borderRadius: '10px',
        },
        data: {},
        selectable: false,
        draggable: false,
        connectable: false,
        focusable: false,
        zIndex: -1,
      }
      const etiqueta: Node = {
        id: `group-label-${g.key}`,
        type: 'etiqueta',
        position: { x: box.x, y: box.y + 2 },
        style: {
          width: box.width,
          border: 'none',
          background: 'transparent',
          padding: 0,
          fontSize: '0.7rem',
          fontWeight: 600,
          color: g.color,
          textAlign: 'center',
          whiteSpace: 'pre-line',
          lineHeight: 1.3,
        },
        data: { label: g.label },
        selectable: false,
        draggable: false,
        connectable: false,
        focusable: false,
        zIndex: -1,
      }
      return [recuadro, etiqueta]
    })

    // `evidence_aggregation`/`persist_decision`: misma categoría
    // determinística, sin recuadro (ver comentario de `ETIQUETAS_SUELTAS`)
    // — sólo el texto, centrado sobre el nodo, arriba de él.
    const etiquetasSueltas: Node[] = ETIQUETAS_SUELTAS.flatMap((e) => {
      const nodo = base.nodes.find((n) => n.id === e.nodeId)
      if (!nodo) return []
      const suelta: Node = {
        id: `loose-label-${e.nodeId}`,
        type: 'etiqueta',
        // Una sola línea (sin paréntesis en la suya) -altura fija propia,
        // no `GROUP_LABEL_HEIGHT` (pensada para las de dos líneas de
        // `GRUPOS`), o quedaría con un hueco de más antes del nodo.
        position: { x: nodo.position.x, y: nodo.position.y - 18 - 4 },
        style: {
          width: NODE_WIDTH,
          border: 'none',
          background: 'transparent',
          padding: 0,
          fontSize: '0.65rem',
          fontWeight: 600,
          color: e.color,
          textAlign: 'center',
        },
        data: { label: e.label },
        selectable: false,
        draggable: false,
        connectable: false,
        focusable: false,
        zIndex: -1,
      }
      return [suelta]
    })

    return { nodes: [...decoracion, ...etiquetasSueltas, ...nodes], edges: base.edges }
  }, [agentRoute, degradedAgents, animating, caseDecided, esMobile])

  return (
    <div
      className={cn(
        'graph-panel-sin-handles w-full rounded-md border',
        // Más alto en vertical: son niveles apilados, no columnas -el
        // ancho ya es 100% del panel, lo que falta es alto para que
        // `fitView` no tenga que encoger tanto el texto.
        esMobile ? 'h-[28rem]' : 'h-80',
      )}
      // Fijo -no `var(--background)`- a propósito: el panel siempre está
      // oscuro, sin importar el tema del sitio. El amarillo/azul/naranja
      // de las etiquetas de categoría (`COLOR_CATEGORIA`) está pensado
      // para leerse sobre un fondo oscuro; en modo claro, sobre el fondo
      // casi blanco del sitio, perdía casi todo el contraste. Tono
      // elegido a mano (no referencia `--background` de `.dark` en
      // `index.css`): tiene que quedar igual aunque alguien cambie ese
      // token ahí.
      style={{ backgroundColor: 'oklch(0.25 0 0)' }}
    >
      {/* Puramente estético, a pedido: los puntos de conexión de React Flow
          (`.react-flow__handle`) no aportan nada acá -`nodesConnectable`
          ya está en `false` en todo el panel, nadie arrastra una arista
          nueva- y tapaban texto en los recuadros. `opacity: 0` en vez de
          `width`/`height: 0`: el tamaño fijo (6px, ver `style.css` de
          `@xyflow/react`) es lo que XYFlow usa para calcular dónde ancla
          cada arista, así que achicarlo correría el punto de anclaje;
          la opacidad no toca esa geometría, sólo lo hace invisible.
          Escapado bajo `.graph-panel-sin-handles` (no un selector global)
          para no afectar otros paneles de grafo de la app si alguna vez
          los hay. */}
      <style>{`
        .graph-panel-sin-handles .react-flow__handle {
          opacity: 0;
        }
      `}</style>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        // Abajo del breakpoint, pinch queda como válvula de escape para
        // acercarse y leer una etiqueta puntual -`fitView` prioriza mostrar
        // el pipeline completo sin recortar nada (por eso no hay `minZoom`:
        // clampear el zoom mínimo aquí cortaba la fila más ancha en vez de
        // encogerla, comprobado a mano con el layout real). En desktop se
        // queda todo apagado, como siempre -es una vista de sólo estado,
        // no un editor-.
        panOnDrag={esMobile}
        zoomOnScroll={false}
        zoomOnPinch={esMobile}
        zoomOnDoubleClick={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
      </ReactFlow>
    </div>
  )
}
