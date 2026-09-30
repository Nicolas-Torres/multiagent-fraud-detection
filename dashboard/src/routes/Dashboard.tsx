import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, XAxis, YAxis } from 'recharts'

import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useIsMobile } from '@/hooks/useIsMobile'
import { CLAVE_COLOR_DECISION, ETIQUETA_DECISION } from '@/lib/etiquetas'

type DecisionType = components['schemas']['DecisionType']

const DECISIONS: DecisionType[] = ['APPROVE', 'CHALLENGE', 'BLOCK', 'ESCALATE_TO_HUMAN']
const CON_SENAL: DecisionType[] = ['CHALLENGE', 'BLOCK', 'ESCALATE_TO_HUMAN']

// Oculta, no borrada: el benchmark de modelos todavía no se corrió, y una
// tarjeta vacía en producción no aporta nada. Se vuelve a `true` cuando exista.
const MOSTRAR_BENCHMARK = false

export function Dashboard() {
  // Agregación en el cliente sobre `GET /cases` — no hay endpoint de
  // agregación (§4.5, decidido): esta vista arranca con lo que ya es
  // servible. `limit` alto porque hoy no hay paginación del lado del
  // agregado; se revisa si el volumen real lo exige.
  const esMobile = useIsMobile()

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
    etiqueta: ETIQUETA_DECISION[d],
    casos: conVeredicto.filter((i) => i.decision === d).length,
  }))
  const tasaEscalamiento =
    conVeredicto.length > 0
      ? (
          (conVeredicto.filter((i) => i.decision === 'ESCALATE_TO_HUMAN').length / conVeredicto.length) * 100
        ).toFixed(1)
      : null

  // `\n` sólo se respeta bajo `md` (`max-md:whitespace-pre-line`, abajo):
  // en mobile las cards van de a dos y el título en una línea las ensancha.
  const stats = [
    { label: 'Transacciones\ntotales', value: casos.data?.total ?? items.length },
    {
      label: 'Políticas\nactivas',
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
          <div className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
            {stats.map((s) => (
              <Card key={s.label}>
                <CardHeader>
                  <CardTitle className="text-sm font-medium text-muted-foreground max-md:whitespace-pre-line">
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
                {/* En mobile, las cuatro etiquetas horizontales no entran y
                    Recharts oculta las que se pisan (`interval` automático):
                    en diagonal entran todas, sin sumar una leyenda. El eje Y
                    angosto (`width`) evita el hueco que dejan sus 60px por
                    defecto para números de dos dígitos. */}
                <ResponsiveContainer width="100%" height={esMobile ? 270 : 240}>
                  <BarChart
                    data={distribucion}
                    margin={{ top: 8, right: esMobile ? 8 : 32, left: 0, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis
                      dataKey="etiqueta"
                      interval={0}
                      tick={{ fontSize: esMobile ? 10 : 11 }}
                      angle={esMobile ? -30 : 0}
                      textAnchor={esMobile ? 'end' : 'middle'}
                      height={esMobile ? 90 : 30}
                    />
                    <YAxis allowDecimals={false} tick={{ fontSize: 12 }} width={28} />
                    {/* Cada barra con el color de su decisión (mejoras2): el mismo
                        que la etiqueta en la tabla, en claro y en oscuro. */}
                    <Bar dataKey="casos" radius={4}>
                      {distribucion.map((d) => (
                        <Cell key={d.decision} fill={`var(--decision-${CLAVE_COLOR_DECISION[d.decision]}-fg)`} />
                      ))}
                    </Bar>
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

      {MOSTRAR_BENCHMARK && (
        <div className="grid gap-4 sm:grid-cols-2">
          <PendingCard
            title="Resultados del benchmark de modelos"
            reason="Corrida manual de DeepEval sobre un golden set curado (scripts/eval_golden_set.py, ADR-0013) — no es un dato que crezca con cada transacción en vivo como el de arriba, así que no se automatizó junto con eso. Encaja mejor como parte de la etapa de CI/imagen/despliegue, donde además tendría sentido correrlo en un job programado."
          />
        </div>
      )}
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
