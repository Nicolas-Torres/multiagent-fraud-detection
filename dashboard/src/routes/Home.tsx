import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api } from '@/api/client'
import { AnalyzingPanel } from '@/components/AnalyzingPanel'
import { DecisionShowcase } from '@/components/DecisionShowcase'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { LIVE_SCENARIOS, transaccionParaCorridaEnVivo } from '@/data/liveScenarios'
import showcaseCasesRaw from '@/data/showcase_cases.json'
import { useCaseProgress } from '@/hooks/useCaseProgress'
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

// Espejo, sólo para la UI, del cooldown real del backend
// (`LIVE_COOLDOWN` en `api/routers/cases.py`) — ese es el que manda, esto
// sólo evita el silencio confuso de clickear "Ejecutar", que el POST
// devuelva 429, y que el panel de abajo se quede mostrando el caso que ya
// estaba seleccionado sin ninguna pista de por qué no pasó nada. No sabe
// de corridas disparadas desde otro navegador — en ese caso, cae al
// mensaje de error reactivo que ya existía.
const COOLDOWN_MS = 10 * 60 * 1000
const STORAGE_KEY = 'ultima-corrida-en-vivo'

function leerUltimasCorridas(): Record<string, number> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as Record<string, number>
  } catch {
    return {}
  }
}

function formatoRestante(ms: number): string {
  const totalSeg = Math.ceil(ms / 1000)
  const min = Math.floor(totalSeg / 60)
  const seg = totalSeg % 60
  return `${min}:${String(seg).padStart(2, '0')}`
}

export function Home() {
  const [selectedId, setSelectedId] = useState<string | null>(CASO_INICIAL)
  const [errorEjecucion, setErrorEjecucion] = useState<string | null>(null)
  const [ultimasCorridas, setUltimasCorridas] = useState<Record<string, number>>(leerUltimasCorridas)
  const [ahora, setAhora] = useState(() => Date.now())
  const queryClient = useQueryClient()

  useEffect(() => {
    const id = setInterval(() => setAhora(Date.now()), 1_000)
    return () => clearInterval(id)
  }, [])

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
    // apenas hay veredicto. El polling sigue siendo la fuente de verdad del
    // veredicto (§4.2); el stream de abajo sólo adelanta el progreso visual.
    refetchInterval: (query) => (query.state.data?.decision ? false : 3_000),
  })

  // Sólo mientras el caso todavía no tiene veredicto: un caso ya decidido
  // no necesita progreso, y el endpoint del stream ya responde "done" de
  // una para un caso terminal (ADR-0018) — esto evita esa ida y vuelta
  // extra en el caso común de elegir un caso de la vitrina ya resuelto.
  const progreso = useCaseProgress(
    selectedId && !detalle.data?.decision ? selectedId : null,
  )

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
    onSuccess: (data, escenarioId) => {
      setErrorEjecucion(null)
      setSelectedId(data.case_id)
      queryClient.invalidateQueries({ queryKey: ['cases'] })
      setUltimasCorridas((previas) => {
        const actualizadas = { ...previas, [escenarioId]: Date.now() }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(actualizadas))
        return actualizadas
      })
    },
    onError: (error: Error) => setErrorEjecucion(error.message),
  })

  function restanteMs(escenarioId: string): number {
    const ultima = ultimasCorridas[escenarioId]
    if (!ultima) return 0
    return Math.max(0, COOLDOWN_MS - (ahora - ultima))
  }

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
          {LIVE_SCENARIOS.map((escenario) => {
            const restante = restanteMs(escenario.id)
            const enCooldown = restante > 0
            return (
              <Card key={escenario.id} className={enCooldown ? 'opacity-60' : undefined}>
                <CardHeader>
                  <CardTitle className="text-sm">{escenario.label}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <p className="text-xs text-muted-foreground">{escenario.description}</p>
                  <Button
                    size="sm"
                    onClick={() => ejecutar.mutate(escenario.id)}
                    disabled={ejecutar.isPending || enCooldown}
                  >
                    {enCooldown ? `Disponible en ${formatoRestante(restante)}` : 'Ejecutar'}
                  </Button>
                </CardContent>
              </Card>
            )
          })}
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
          <AnalyzingPanel
            status={detalle.data.status}
            ranNodes={progreso.ranNodes}
            connected={progreso.connected}
          />
        )}
        {selectedId && detalle.data?.decision && (
          <DecisionShowcase decision={detalle.data.decision} />
        )}
      </section>


    </div>
  )
}
