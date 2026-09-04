import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from 'recharts'

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

type DecisionType = components['schemas']['DecisionType']

const DECISIONS: DecisionType[] = ['APPROVE', 'CHALLENGE', 'BLOCK', 'ESCALATE_TO_HUMAN']
const CON_SENAL: DecisionType[] = ['CHALLENGE', 'BLOCK', 'ESCALATE_TO_HUMAN']

export function Dashboard() {
  // Agregación en el cliente sobre `GET /cases` — no hay endpoint de
  // agregación (§4.5, decidido): esta vista arranca con lo que ya es
  // servible. `limit` alto porque hoy no hay paginación del lado del
  // agregado; se revisa si el volumen real lo exige.
  const casos = useQuery({
    queryKey: ['cases', 'all-for-dashboard'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/cases', { params: { query: { limit: 200 } } })
      if (error) throw error
      return data
    },
  })

  const politicas = useQuery({
    queryKey: ['policies'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/policies')
      if (error) throw error
      return data
    },
  })

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

  const cargando = casos.isLoading || politicas.isLoading
  const conError = casos.isError || politicas.isError

  const items = casos.data?.items ?? []
  const conVeredicto = items.filter((i) => i.decision !== null)
  const distribucion = DECISIONS.map((d) => ({
    decision: d,
    casos: conVeredicto.filter((i) => i.decision === d).length,
  }))
  const tasaEscalamiento =
    conVeredicto.length > 0
      ? (
          (conVeredicto.filter((i) => i.decision === 'ESCALATE_TO_HUMAN').length / conVeredicto.length) * 100
        ).toFixed(1)
      : null

  const stats = [
    { label: 'Transacciones totales', value: casos.data?.total ?? items.length },
    {
      label: 'Políticas activas',
      value: politicas.data?.filter((p) => p.state === 'active').length ?? 0,
    },
    {
      label: 'Con señal',
      value: conVeredicto.filter((i) => i.decision && CON_SENAL.includes(i.decision)).length,
    },
    { label: 'Aprobadas', value: conVeredicto.filter((i) => i.decision === 'APPROVE').length },
  ]

  return (
    <div className="space-y-6">
      {cargando ? (
        <Skeleton className="h-24 w-full" />
      ) : conError ? (
        <p className="text-destructive">No se pudieron cargar los datos.</p>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {stats.map((s) => (
              <Card key={s.label}>
                <CardHeader>
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    {s.label}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-3xl font-semibold">{s.value}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Distribución de decisiones</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={distribucion}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis dataKey="decision" tick={{ fontSize: 12 }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                    <Bar dataKey="casos" fill="var(--primary)" radius={4} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Tasa de escalamiento a humano</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-4xl font-semibold">
                  {tasaEscalamiento === null ? '—' : `${tasaEscalamiento}%`}
                </p>
                <p className="text-sm text-muted-foreground">
                  de {conVeredicto.length} casos con veredicto
                </p>
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <LatenciaYCostoPorNodo metricas={metricas} />

      <div className="grid gap-4 sm:grid-cols-2">
        <PendingCard
          title="Resultados del benchmark de modelos"
          reason="Corrida manual de DeepEval sobre un golden set curado (scripts/eval_golden_set.py, ADR-0013) — no es un dato que crezca con cada transacción en vivo como el de arriba, así que no se automatizó junto con eso. Encaja mejor como parte de la etapa de CI/imagen/despliegue, donde además tendría sentido correrlo en un job programado."
        />
      </div>
    </div>
  )
}

type LlmMetricsRead = components['schemas']['LlmMetricsRead']

function formatUsd(valor: number): string {
  return `$${valor.toFixed(valor < 1 ? 4 : 2)}`
}

function LatenciaYCostoPorNodo({
  metricas,
}: {
  metricas: { isLoading: boolean; isError: boolean; data: LlmMetricsRead | undefined }
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Costo y latencia por nodo</CardTitle>
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
                  <TableHead>Corridas</TableHead>
                  <TableHead>Latencia prom.</TableHead>
                  <TableHead>Tokens prom.</TableHead>
                  <TableHead>Costo prom.</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {metricas.data.nodes!.map((n) => (
                  <TableRow key={n.name}>
                    <TableCell className="font-mono text-xs">{n.name}</TableCell>
                    <TableCell className="text-muted-foreground">{n.run_count}</TableCell>
                    <TableCell>{n.avg_latency_seconds.toFixed(2)}s</TableCell>
                    <TableCell className="text-muted-foreground">
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

function PendingCard({ title, reason }: { title: string; reason: string }) {
  return (
    <Card className="border-dashed">
      <CardHeader>
        <CardTitle className="text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">Sin datos todavía. {reason}</p>
      </CardContent>
    </Card>
  )
}
