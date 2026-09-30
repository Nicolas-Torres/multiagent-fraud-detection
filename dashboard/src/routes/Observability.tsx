import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { Field } from '@/components/Field'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import topology from '@/data/graph_topology.json'
import { useCaseProgress } from '@/hooks/useCaseProgress'
import { cn } from '@/lib/utils'

// Cuánto dura el destello de "esto acaba de cambiar" en la tabla de costo
// tras un refresco forzado (ver más abajo) — sólo lo justo para que el ojo
// lo note, no una animación que se quede pegada.
const DURACION_DESTELLO_MS = 1_200

// Un análisis tarda entre 15 y 40 s: un caso en `ANALYZING` con más de 2
// minutos no está corriendo, quedó trabado por un reinicio (mejoras2). No
// enciende el indicador; el backend lo cierra como `FAILED` al arrancar.
const ANTIGUEDAD_MAXIMA_EN_VIVO_MS = 2 * 60 * 1000

/**
 * Observabilidad (mejoras2): costo y latencia reales de cada nodo del grafo,
 * leídos de LangSmith. Antes vivía al pie del Dashboard, compitiendo con los
 * números que le importan a cualquier visitante; acá es para quien quiere ver
 * cómo se comporta el sistema por dentro.
 */
export function Observability() {
  const queryClient = useQueryClient()

  // Costo/latencia reales del grafo, leídos de LangSmith (ADR-0019) — sin
  // acción del usuario: sube solo con cada ejecución de cualquier
  // visitante. 30s de refetch, igual al TTL de caché del backend: pedirlo
  // más seguido no traería nada distinto.
  const metricas = useQuery({
    queryKey: ['metrics', 'llm'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/metrics/llm')
      if (error) throw error
      return data
    },
    refetchInterval: 30_000,
  })

  // Descubre si hay algo corriendo ahora mismo — sin importar quién lo
  // disparó ni desde qué pestaña (mismo filtro que ya usa la Cola,
  // `Queue.tsx`). 8s: "se ve vivo" sin saturar la API.
  const enCurso = useQuery({
    queryKey: ['cases', 'ANALYZING'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/cases', {
        params: { query: { status: 'ANALYZING', limit: 1 } },
      })
      if (error) throw error
      return data
    },
    refetchInterval: 8_000,
  })
  const casoEnCurso = enCurso.data?.items[0]
  const caseIdEnCurso =
    casoEnCurso && Date.now() - new Date(casoEnCurso.created_at).getTime() < ANTIGUEDAD_MAXIMA_EN_VIVO_MS
      ? casoEnCurso.case_id
      : null

  // Sólo para el destello de "esto acaba de cambiar" (§ más abajo) — no
  // gobierna nada de la lógica de refresco en sí.
  const [justoActualizado, setJustoActualizado] = useState(false)

  // Al terminar, refresca la tabla de costo en el mismo instante en vez de
  // esperar el próximo ciclo de 30s — pide el dato fresco con `force=true`
  // (ADR-0020) y lo escribe directo en la caché de la query. Va como
  // callback de `useCaseProgress`, no como efecto que mire `progreso.done`
  // después: el sondeo de "hay algo en ANALYZING" (arriba) puede dejar de
  // encontrar este caso justo cuando termina, resetear `caseIdEnCurso` a
  // `null`, y con él `done` -un efecto dependiente de `done` se cancelaría
  // a mitad de camino por esa razón ajena, sin llegar a refrescar nada.
  // El valor de retorno no se usa acá -sólo el callback-, pero el hook
  // igual hay que llamarlo para que abra la conexión SSE.
  useCaseProgress(caseIdEnCurso, () => {
    void (async () => {
      const { data, error } = await api.GET('/api/v1/metrics/llm', {
        params: { query: { force: true } },
      })
      if (!error) {
        queryClient.setQueryData(['metrics', 'llm'], data)
        setJustoActualizado(true)
        setTimeout(() => setJustoActualizado(false), DURACION_DESTELLO_MS)
      }
    })()
  })

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Costo y latencia reales de cada nodo del grafo, medidos en LangSmith sobre las
        transacciones analizadas. Se actualiza solo cuando termina un análisis.
      </p>
      <LatenciaYCostoPorNodo
        metricas={metricas}
        enVivo={Boolean(caseIdEnCurso)}
        justoActualizado={justoActualizado}
      />
    </div>
  )
}

type LlmMetricsRead = components['schemas']['LlmMetricsRead']

// Mismo nombre que muestra el grafo (`GraphPanel`), no el id técnico del
// nodo: la tabla y el grafo describen los mismos diez pasos.
const ETIQUETA_NODO = new Map(topology.nodes.map((n) => [n.id, n.label]))

function formatUsd(valor: number): string {
  return `$${valor.toFixed(valor < 1 ? 4 : 2)}`
}

function LatenciaYCostoPorNodo({
  metricas,
  enVivo,
  justoActualizado,
}: {
  metricas: { isLoading: boolean; isError: boolean; data: LlmMetricsRead | undefined }
  /** Hay un caso en `ANALYZING` ahora mismo -de cualquier origen, no sólo
   * de esta pestaña (ADR-0020). Sólo enciende el badge; no cambia nada de
   * lo que se muestra en la tabla. */
  enVivo: boolean
  /** El refresco forzado por `done` (ADR-0020) acaba de llegar -destello
   * breve para marcar el momento, no un estado permanente. */
  justoActualizado: boolean
}) {
  return (
    <Card className={cn('transition-shadow duration-700', justoActualizado && 'ring-2 ring-emerald-500/60')}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Costo y latencia por nodo
          {enVivo && (
            <span className="flex items-center gap-1.5 text-xs font-normal text-muted-foreground">
              <span className="relative flex size-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-75" />
                <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
              </span>
              Analizando en vivo
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {metricas.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : metricas.isError || !metricas.data?.available ? (
          <p className="text-sm text-muted-foreground">
            Sin datos todavía. Requiere `LANGSMITH_TRACING`/`LANGSMITH_API_KEY`
            configurados y que LangSmith responda — ver ADR-0019.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
              <Field label="Costo total" value={formatUsd(metricas.data.summary!.total_cost)} />
              <Field
                label="Costo / decisión"
                value={formatUsd(metricas.data.summary!.avg_cost_per_decision)}
              />
              <Field
                label="Latencia p50"
                value={`${metricas.data.summary!.latency_p50_seconds.toFixed(1)}s`}
              />
              <Field
                label="Tasa de error"
                value={`${(metricas.data.summary!.error_rate * 100).toFixed(1)}%`}
              />
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nodo</TableHead>
                  <TableHead className="hidden @3xl:table-cell">Corridas</TableHead>
                  <TableHead>
                    Latencia <br className="md:hidden" />
                    prom.
                  </TableHead>
                  <TableHead className="hidden @3xl:table-cell">Tokens prom.</TableHead>
                  <TableHead>
                    Costo <br className="md:hidden" />
                    prom.
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {metricas.data.nodes!.map((n) => (
                  <TableRow key={n.name}>
                    <TableCell className="whitespace-normal">
                      {ETIQUETA_NODO.get(n.name) ?? n.name}
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground @3xl:table-cell">
                      {n.run_count}
                    </TableCell>
                    <TableCell>{n.avg_latency_seconds.toFixed(2)}s</TableCell>
                    <TableCell className="hidden text-muted-foreground @3xl:table-cell">
                      {n.avg_tokens > 0 ? Math.round(n.avg_tokens) : '—'}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {n.avg_cost > 0 ? formatUsd(n.avg_cost) : '—'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
