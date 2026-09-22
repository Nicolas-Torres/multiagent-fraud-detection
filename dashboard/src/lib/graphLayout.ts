import { Position, type Edge, type Node } from '@xyflow/react'

interface TopologyNode {
  id: string
  synthetic: boolean
  // Etiqueta de exhibición (`START`/`END` para los nodos sintéticos, el
  // nombre del agente para el resto) — separada del `id` a propósito: la
  // lógica de este archivo (raíz del BFS, más abajo) sigue comparando
  // contra `id`, nunca contra esto.
  label: string
}

interface TopologyEdge {
  source: string
  target: string
  conditional: boolean
}

export interface Topology {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
}

const COL_GAP = 200
const ROW_GAP = 90

export type GraphDirection = 'horizontal' | 'vertical'

/**
 * Posiciona por nivel topológico (distancia más larga desde `__start__`), no
 * por orden de `agent_route`. `agent_route` es una secuencia de supersteps
 * **aplanada** sin precedencia causal dentro de un grupo (contrato §2.5) —
 * ramas del mismo nivel se dibujan una al lado de la otra, nunca en cadena,
 * para no sugerir un orden que el sistema no garantiza.
 *
 * `direction: 'vertical'` (mobile, GraphPanel bajo el breakpoint) no es un
 * espejo ingenuo de x/y: `COL_GAP` está calibrado contra `NODE_WIDTH` (170,
 * en `GraphPanel.tsx`) y `ROW_GAP` contra `NODE_HEIGHT` (40) — así que
 * `COL_GAP` se queda siempre en el eje X y `ROW_GAP` siempre en el eje Y,
 * sin importar si ese eje representa el nivel o los hermanos. Lo único que
 * cambia con `direction` es *cuál* de las dos (nivel o índice de hermano)
 * maneja cada eje.
 */
export function layoutTopology(
  topology: Topology,
  direction: GraphDirection = 'horizontal',
): { nodes: Node[]; edges: Edge[] } {
  const children = new Map<string, string[]>()
  for (const e of topology.edges) {
    children.set(e.source, [...(children.get(e.source) ?? []), e.target])
  }

  const level = new Map<string, number>()
  const start = topology.nodes.find((n) => n.id === '__start__')?.id ?? topology.nodes[0].id
  level.set(start, 0)

  // BFS por niveles: el nivel de un nodo es la distancia más larga conocida
  // desde `__start__`, así que un nodo con varios padres espera a que todos
  // se hayan visitado antes de fijar su nivel definitivo.
  let frontier = [start]
  const visited = new Set(frontier)
  while (frontier.length > 0) {
    const next: string[] = []
    for (const id of frontier) {
      for (const child of children.get(id) ?? []) {
        const candidato = (level.get(id) ?? 0) + 1
        if (!level.has(child) || candidato > (level.get(child) ?? 0)) {
          level.set(child, candidato)
        }
        if (!visited.has(child)) {
          visited.add(child)
          next.push(child)
        }
      }
    }
    frontier = next
  }

  const porNivel = new Map<number, string[]>()
  for (const n of topology.nodes) {
    const lvl = level.get(n.id) ?? 0
    porNivel.set(lvl, [...(porNivel.get(lvl) ?? []), n.id])
  }

  const nodes: Node[] = topology.nodes.map((n) => {
    const lvl = level.get(n.id) ?? 0
    const fila = porNivel.get(lvl) ?? []
    const idx = fila.indexOf(n.id)
    const offset = (fila.length - 1) / 2
    const position =
      direction === 'vertical'
        ? { x: (idx - offset) * COL_GAP, y: lvl * ROW_GAP }
        : { x: lvl * COL_GAP, y: (idx - offset) * ROW_GAP }
    return {
      id: n.id,
      position,
      // `level` viaja en `data` para que `GraphPanel` pueda escalonar la
      // animación de "analizando" en el mismo orden topológico que ya
      // gobierna el layout — un nodo no puede "pulsar antes" que sus
      // padres sin contradecir lo que el propio grafo garantiza.
      data: { label: n.label, level: lvl },
      // Estilo real (color por estado de ejecución) lo aplica GraphPanel;
      // acá sólo la geometría.
      style: { width: 170 },
      // En horizontal el flujo es izquierda→derecha; en vertical,
      // arriba→abajo. Sin esto, React Flow usa el default del tipo
      // `default` (`Top`/`Bottom` fijo), que en modo horizontal dibuja cada
      // conector saliendo por arriba/abajo del nodo y obliga a una curva
      // innecesaria para volver a la horizontal.
      sourcePosition: direction === 'vertical' ? Position.Bottom : Position.Right,
      targetPosition: direction === 'vertical' ? Position.Top : Position.Left,
    }
  })

  const edges: Edge[] = topology.edges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    animated: false,
  }))

  return { nodes, edges }
}
