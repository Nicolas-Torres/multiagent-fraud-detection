import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from 'recharts'

import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

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

      <div className="grid gap-4 sm:grid-cols-2">
        <PendingCard
          title="Latencia y costo por nodo"
          reason="Depende del wiring de LangSmith al backend — conectado (langsmith.wrappers.wrap_anthropic), pero todavía sin un camino que traiga esos datos a este dashboard. Ver briefing_dashboard.md §4.5."
        />
        <PendingCard
          title="Resultados del benchmark de modelos"
          reason="Falta ubicar dónde vive ese resultado hoy (¿DeepEval?, ¿un script suelto?) antes de poder servirlo acá."
        />
      </div>
    </div>
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
