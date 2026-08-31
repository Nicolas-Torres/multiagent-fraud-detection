import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { AnalyzingPanel } from '@/components/AnalyzingPanel'
import { DecisionShowcase } from '@/components/DecisionShowcase'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import diverseScenariosRaw from '@/data/diverse_scenarios.json'
import { LIVE_SCENARIOS, type LiveScenario, transaccionParaCorridaEnVivo } from '@/data/liveScenarios'
import showcaseCasesRaw from '@/data/showcase_cases.json'
import { useCaseProgress } from '@/hooks/useCaseProgress'
import { decisionVariant } from '@/lib/badges'
import { formatAmount } from '@/lib/format'
import { cn } from '@/lib/utils'

type TransactionIn = components['schemas']['TransactionIn']

interface ShowcaseCase {
  case_id: string
  transaction_id: string
  label: string
  id: string
  payload: Omit<TransactionIn, 'transaction_id'>
}

const showcaseCases = showcaseCasesRaw as ShowcaseCase[]
const diverseScenarios = diverseScenariosRaw as LiveScenario[]

// El desafiado (CHALLENGE) es el más representativo para el primer vistazo:
// tiene señal, cita, debate y confianza intermedia — el resto queda a un
// click en la tabla de abajo.
const CASO_INICIAL = showcaseCases[1]?.case_id ?? showcaseCases[0]?.case_id ?? null

// Espejo, sólo para la UI, del cooldown real del backend (`LIVE_COOLDOWN` en
// `api/routers/cases.py`) — ese es el que manda, esto sólo evita el
// silencio confuso de clickear "Ejecutar" y que no pase nada visible.
// Cubre las tres fuentes de fila (vitrina, escenarios fijos, diversos): las
// tres comparten el mismo backend y el mismo prefijo `LIVE-`.
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

export function Transactions() {
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
    // Mientras no haya decisión el caso puede seguir avanzando — se deja de
    // sondear apenas hay veredicto. El polling sigue siendo la fuente de
    // verdad (§4.2); el stream de abajo sólo adelanta el progreso visual.
    refetchInterval: (query) => (query.state.data?.decision ? false : 3_000),
  })

  const progreso = useCaseProgress(
    selectedId && !detalle.data?.decision ? selectedId : null,
  )

  const ejecutar = useMutation({
    mutationFn: async (escenario: Pick<LiveScenario, 'id' | 'payload'>) => {
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
    onSuccess: (data, escenario) => {
      setErrorEjecucion(null)
      setSelectedId(data.case_id)
      queryClient.invalidateQueries({ queryKey: ['cases'] })
      setUltimasCorridas((previas) => {
        const actualizadas = { ...previas, [escenario.id]: Date.now() }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(actualizadas))
        return actualizadas
      })
    },
    onError: (error: Error) => setErrorEjecucion(error.message),
  })

  function restanteMs(id: string): number {
    const ultima = ultimasCorridas[id]
    if (!ultima) return 0
    return Math.max(0, COOLDOWN_MS - (ahora - ultima))
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Transacciones</h1>
        <p className="text-muted-foreground">
          Cada fila es una transacción real, evaluada por el grafo de agentes real.
          Elegí una ya resuelta para ver su análisis, o ejecutá cualquiera en vivo y
          mirá correr los nueve agentes.
        </p>
      </div>

      {/* Panel fijo: reacciona a la fila elegida o a la que está corriendo. */}
      <section>
        {!selectedId && (
          <p className="text-muted-foreground">Elegí una fila de la tabla para verla acá.</p>
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

      <section className="space-y-3">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Escenario</TableHead>
              <TableHead>Cliente</TableHead>
              <TableHead>Monto</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>Acción</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <SeccionFila titulo="Casos reales" />
            {showcaseCases.map((item) => (
              <FilaVitrina
                key={item.case_id}
                item={item}
                seleccionado={selectedId === item.case_id}
                restante={restanteMs(item.id)}
                onSeleccionar={() => setSelectedId(item.case_id)}
                onEjecutar={() => ejecutar.mutate(item)}
                ejecutando={ejecutar.isPending}
              />
            ))}

            <SeccionFila titulo="Ejecutar en vivo" />
            {LIVE_SCENARIOS.map((escenario) => (
              <FilaEscenario
                key={escenario.id}
                escenario={escenario}
                restante={restanteMs(escenario.id)}
                onEjecutar={() => ejecutar.mutate(escenario)}
                ejecutando={ejecutar.isPending}
              />
            ))}

            <SeccionFila titulo="Más escenarios reales" />
            {diverseScenarios.map((escenario) => (
              <FilaEscenario
                key={escenario.id}
                escenario={escenario}
                restante={restanteMs(escenario.id)}
                onEjecutar={() => ejecutar.mutate(escenario)}
                ejecutando={ejecutar.isPending}
              />
            ))}
          </TableBody>
        </Table>
        {errorEjecucion && <p className="text-sm text-destructive">{errorEjecucion}</p>}
      </section>
    </div>
  )
}

function SeccionFila({ titulo }: { titulo: string }) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={5} className="bg-muted/50 text-xs font-medium text-muted-foreground">
        {titulo}
      </TableCell>
    </TableRow>
  )
}

function FilaVitrina({
  item,
  seleccionado,
  restante,
  onSeleccionar,
  onEjecutar,
  ejecutando,
}: {
  item: ShowcaseCase
  seleccionado: boolean
  restante: number
  onSeleccionar: () => void
  onEjecutar: () => void
  ejecutando: boolean
}) {
  // Comparte caché con el panel fijo (misma `queryKey`) cuando esta fila es
  // la seleccionada — no es una segunda llamada de red, React Query la
  // deduplica.
  const detalle = useQuery({
    queryKey: ['case', item.case_id],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/cases/{case_id}', {
        params: { path: { case_id: item.case_id } },
      })
      if (error) throw error
      return data
    },
  })
  const enCooldown = restante > 0

  return (
    <TableRow
      className={cn('cursor-pointer', seleccionado && 'bg-secondary')}
      onClick={onSeleccionar}
    >
      <TableCell className="font-medium">{item.label}</TableCell>
      <TableCell className="text-muted-foreground">{item.payload.customer_id}</TableCell>
      <TableCell>{formatAmount(String(item.payload.amount), item.payload.currency)}</TableCell>
      <TableCell>
        {detalle.data?.decision ? (
          <Badge variant={decisionVariant(detalle.data.decision.decision)}>
            {detalle.data.decision.decision}
          </Badge>
        ) : detalle.data ? (
          <Badge variant="outline">{detalle.data.status}</Badge>
        ) : (
          <Skeleton className="h-5 w-16" />
        )}
      </TableCell>
      <TableCell>
        <Button
          size="sm"
          variant="outline"
          onClick={(e) => {
            e.stopPropagation()
            onEjecutar()
          }}
          disabled={ejecutando || enCooldown}
        >
          {enCooldown ? formatoRestante(restante) : 'Volver a ejecutar'}
        </Button>
      </TableCell>
    </TableRow>
  )
}

function FilaEscenario({
  escenario,
  restante,
  onEjecutar,
  ejecutando,
}: {
  escenario: LiveScenario
  restante: number
  onEjecutar: () => void
  ejecutando: boolean
}) {
  const enCooldown = restante > 0

  return (
    <TableRow>
      <TableCell className="font-medium">
        {escenario.label}
        <p className="text-xs font-normal text-muted-foreground">{escenario.description}</p>
      </TableCell>
      <TableCell className="text-muted-foreground">{escenario.payload.customer_id}</TableCell>
      <TableCell>
        {formatAmount(String(escenario.payload.amount), escenario.payload.currency)}
      </TableCell>
      <TableCell className="text-muted-foreground">—</TableCell>
      <TableCell>
        <Button size="sm" onClick={onEjecutar} disabled={ejecutando || enCooldown}>
          {enCooldown ? `Disponible en ${formatoRestante(restante)}` : 'Ejecutar'}
        </Button>
      </TableCell>
    </TableRow>
  )
}
