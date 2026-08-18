import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '@/api/client'
import { AnalyzingPanel } from '@/components/AnalyzingPanel'
import { DecisionShowcase } from '@/components/DecisionShowcase'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { LIVE_SCENARIOS, transaccionParaCorridaEnVivo } from '@/data/liveScenarios'
import showcaseCasesRaw from '@/data/showcase_cases.json'
import { cn } from '@/lib/utils'

interface ShowcaseCase {
  case_id: string
  transaction_id: string
  label: string
}

const showcaseCases = showcaseCasesRaw as ShowcaseCase[]

// El desafiado (CHALLENGE) es el más representativo para el primer
// vistazo: tiene señal, cita, debate y confianza intermedia — el resto de
// la vitrina queda a un clic.
const CASO_INICIAL = showcaseCases[1]?.case_id ?? showcaseCases[0]?.case_id ?? null

export function Home() {
  const [selectedId, setSelectedId] = useState<string | null>(CASO_INICIAL)
  const [errorEjecucion, setErrorEjecucion] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const detalle = useQuery({
    queryKey: ['case', selectedId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/cases/{case_id}', {
        params: { path: { case_id: selectedId! } },
      })
      if (error) throw error
      return data
    },
    enabled: !!selectedId,
    // Mientras no haya decisión el caso puede seguir avanzando
    // (RECEIVED → ANALYZING → DECIDED/PENDING_HUMAN) — se deja de sondear
    // apenas hay veredicto. Polling, nunca WebSocket (§4.2, ya decidido).
    refetchInterval: (query) => (query.state.data?.decision ? false : 3_000),
  })

  const ejecutar = useMutation({
    mutationFn: async (escenarioId: string) => {
      const escenario = LIVE_SCENARIOS.find((e) => e.id === escenarioId)!
      const { data, error, response } = await api.POST('/api/v1/cases', {
        body: transaccionParaCorridaEnVivo(escenario),
      })
      if (error) {
        if (response.status === 429) {
          throw new Error('Este escenario se corrió hace poco — probá de nuevo en unos minutos.')
        }
        throw new Error('No se pudo iniciar el análisis.')
      }
      return data
    },
    onSuccess: (data) => {
      setErrorEjecucion(null)
      setSelectedId(data.case_id)
      queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: (error: Error) => setErrorEjecucion(error.message),
  })

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Sistema multi-agente de detección de fraude</h1>
        <p className="text-muted-foreground">
          Cada tarjeta de abajo es una transacción real, evaluada por el grafo de agentes
          real. Elegí un caso ya resuelto, o disparás uno en vivo y mirás correr los nueve
          agentes.
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Casos reales</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {showcaseCases.map((c) => (
            <button
              key={c.case_id}
              type="button"
              onClick={() => setSelectedId(c.case_id)}
              className={cn(
                'rounded-md border p-3 text-left text-sm transition-colors hover:border-primary',
                selectedId === c.case_id && 'border-primary bg-secondary',
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Ejecutar un escenario en vivo</h2>
        <p className="text-sm text-muted-foreground">
          Mismos datos reales que arriba — se vuelven a correr con una transacción
          nueva, ahora mismo, para que veas el análisis completo en vivo.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          {LIVE_SCENARIOS.map((escenario) => (
            <Card key={escenario.id}>
              <CardHeader>
                <CardTitle className="text-sm">{escenario.label}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-muted-foreground">{escenario.description}</p>
                <Button
                  size="sm"
                  onClick={() => ejecutar.mutate(escenario.id)}
                  disabled={ejecutar.isPending}
                >
                  Ejecutar
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
        {errorEjecucion && <p className="text-sm text-destructive">{errorEjecucion}</p>}
      </section>
      
      {/* Panel fijo: reacciona al caso elegido o al que está corriendo. */}
      <section>
        {!selectedId && (
          <p className="text-muted-foreground">Elegí un caso de la lista para verlo acá.</p>
        )}
        {selectedId && detalle.isLoading && <Skeleton className="h-96 w-full" />}
        {selectedId && detalle.isError && (
          <p className="text-destructive">No se pudo cargar el caso.</p>
        )}
        {selectedId && detalle.data && !detalle.data.decision && (
          <AnalyzingPanel status={detalle.data.status} />
        )}
        {selectedId && detalle.data?.decision && (
          <DecisionShowcase decision={detalle.data.decision} />
        )}
      </section>


    </div>
  )
}
