import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDownIcon } from 'lucide-react'
import { useEffect, useState } from 'react'

import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { AnalyzingPanel } from '@/components/AnalyzingPanel'
import { DecisionDetail, GraphSection } from '@/components/DecisionShowcase'
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
import { formatAmount, formatDateTime, formatTransactionId } from '@/lib/format'
import { cn } from '@/lib/utils'

type TransactionIn = components['schemas']['TransactionIn']
type CaseDetailType = components['schemas']['CaseDetail']

interface ShowcaseCase {
  case_id: string
  transaction_id: string
  label: string
  id: string
  payload: Omit<TransactionIn, 'transaction_id'>
}

const NUM_COLUMNAS = 10

const showcaseCases = showcaseCasesRaw as ShowcaseCase[]
const diverseScenarios = diverseScenariosRaw as LiveScenario[]

// Un solo grupo "Ejecutar en vivo": los tres escenarios ancla y los
// generados desde el dataset real se disparan y se muestran exactamente
// igual — separarlos en dos encabezados no comunicaba ninguna diferencia
// visible.
const escenariosEnVivo: LiveScenario[] = [...LIVE_SCENARIOS, ...diverseScenarios]

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

// Mismo motivo que `ultimasCorridas`: sin esto, el `case_id` de una fila en
// vivo/diversa vive sólo en memoria y se pierde al cambiar de pestaña — la
// fila vuelve a mostrar "—" como si nunca se hubiera ejecutado, aunque el
// caso ya esté decidido en el backend.
const CASE_IDS_STORAGE_KEY = 'ultimo-case-id-por-escenario'

function leerCaseIdsPorEscenario(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(CASE_IDS_STORAGE_KEY) ?? '{}') as Record<string, string>
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
  // Sólo para las filas en vivo/diversas: no tienen `case_id` hasta el
  // primer "Ejecutar" — una vez que lo tienen, esta fila puede consultar y
  // mostrar su propia "Decisión del LLM" igual que una de vitrina.
  const [caseIdPorEscenario, setCaseIdPorEscenario] =
    useState<Record<string, string>>(leerCaseIdsPorEscenario)
  const [ahora, setAhora] = useState(() => Date.now())
  const queryClient = useQueryClient()

  useEffect(() => {
    const id = setInterval(() => setAhora(Date.now()), 1_000)
    return () => clearInterval(id)
  }, [])

  // Panel fijo de arriba — sin cambios de comportamiento: reacciona a la
  // fila de vitrina elegida o a la que se acaba de disparar en vivo.
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
      setCaseIdPorEscenario((previos) => {
        const actualizados = { ...previos, [escenario.id]: data.case_id }
        localStorage.setItem(CASE_IDS_STORAGE_KEY, JSON.stringify(actualizados))
        return actualizados
      })
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
      <p className="text-muted-foreground">
        Cada fila es una transacción real, evaluada por el grafo de agentes real.
        Elegí una ya resuelta para ver su análisis, o ejecutá cualquiera en vivo y
        mirá correr los nueve agentes.
      </p>

      {/* Panel fijo: reacciona a la fila elegida o a la que está corriendo
          — mismo mecanismo de siempre, sin cambios. */}
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
          <GraphSection decision={detalle.data.decision} />
        )}
      </section>

      <section className="space-y-3">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Acción</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>Decisión del LLM</TableHead>
              <TableHead className="border-l">Transacción</TableHead>
              <TableHead>Cliente</TableHead>
              <TableHead>Monto</TableHead>
              <TableHead>Canal</TableHead>
              <TableHead>País</TableHead>
              <TableHead>Banco</TableHead>
              <TableHead>Fecha</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {showcaseCases.map((item) => (
              <FilaTransaccion
                key={item.case_id}
                claveEscenario={item.id}
                transactionId={item.transaction_id}
                payload={item.payload}
                caseId={item.case_id}
                restante={restanteMs(item.id)}
                accionLabel="Ejecutar"
                onEjecutar={() => ejecutar.mutate(item)}
                ejecutando={ejecutar.isPending}
              />
            ))}

            {escenariosEnVivo.map((escenario) => (
              <FilaTransaccion
                key={escenario.id}
                claveEscenario={escenario.id}
                transactionId={null}
                payload={escenario.payload}
                caseId={caseIdPorEscenario[escenario.id] ?? null}
                restante={restanteMs(escenario.id)}
                accionLabel="Ejecutar"
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

/**
 * Una fila por transacción, real o candidata a ejecutarse — reemplaza a
 * `FilaVitrina`/`FilaEscenario`, que hoy están casi duplicadas. La
 * diferencia entre "ya tiene caso" (vitrina) y "todavía no" (en vivo,
 * antes del primer click) es sólo si `caseId` es `null`: la consulta se
 * desactiva y "Estado"/"Decisión del LLM" quedan en `—` hasta que exista.
 */
function FilaTransaccion({
  claveEscenario,
  transactionId,
  payload,
  caseId,
  restante,
  accionLabel,
  onEjecutar,
  ejecutando,
}: {
  claveEscenario: string
  transactionId: string | null
  payload: Omit<TransactionIn, 'transaction_id'>
  caseId: string | null
  restante: number
  accionLabel: string
  onEjecutar: () => void
  ejecutando: boolean
}) {
  const [detalleAbierto, setDetalleAbierto] = useState(false)

  // Misma `queryKey` que ya usa el panel fijo de arriba para este mismo
  // caso -React Query la deduplica, cero costo de red extra.
  const detalle = useQuery({
    queryKey: ['case', caseId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/cases/{case_id}', {
        params: { path: { case_id: caseId! } },
      })
      if (error) throw error
      return data as CaseDetailType
    },
    enabled: !!caseId,
  })
  const enCooldown = restante > 0

  return (
    <>
      <TableRow>
        <TableCell>
          <Button
            className="cursor-pointer"
            size="sm"
            variant="outline"
            onClick={onEjecutar}
            disabled={ejecutando || enCooldown}
          >
            {enCooldown ? formatoRestante(restante) : accionLabel}
          </Button>
        </TableCell>
        <TableCell>
          {!caseId ? (
            <span className="text-muted-foreground">—</span>
          ) : detalle.isLoading ? (
            <Skeleton className="h-5 w-20" />
          ) : detalle.data ? (
            <Badge variant="outline">{detalle.data.status}</Badge>
          ) : null}
        </TableCell>
        <TableCell>
          {detalle.data?.decision ? (
            <button
              type="button"
              className="flex cursor-pointer items-center gap-1"
              onClick={() => setDetalleAbierto((v) => !v)}
            >
              <Badge variant={decisionVariant(detalle.data.decision.decision)}>
                {detalle.data.decision.decision}
              </Badge>
              <ChevronDownIcon
                className={cn(
                  'size-4 text-muted-foreground transition-transform',
                  detalleAbierto && 'rotate-180',
                )}
              />
            </button>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </TableCell>
        <TableCell className="text-muted-foreground border-l">
          {formatTransactionId(detalle.data?.transaction.transaction_id ?? transactionId ?? '—')}
        </TableCell>
        <TableCell className="text-muted-foreground">{payload.customer_id}</TableCell>
        <TableCell>{formatAmount(String(payload.amount), payload.currency)}</TableCell>
        <TableCell className="text-muted-foreground">{payload.channel.toUpperCase()}</TableCell>
        <TableCell className="text-muted-foreground">{payload.country}</TableCell>
        <TableCell className="text-muted-foreground">{payload.issuer_bank ?? '—'}</TableCell>
        <TableCell className="text-muted-foreground">
          {formatDateTime(payload.timestamp)}
        </TableCell>
      </TableRow>
      {detalleAbierto && detalle.data?.decision && (
        <TableRow className="hover:bg-transparent" key={`${claveEscenario}-detalle`}>
          {/* `whitespace-normal` pisa el `whitespace-nowrap` por defecto de
              `TableCell` (pensado para datos tabulares) — si no, cada
              párrafo/valor del detalle se estira en una sola línea sin
              cortar. El tope de ancho evita que ese contenido, que no es
              tabular, herede el ancho completo de una tabla de 10 columnas
              (más ancha que la página) y obligue a scrollear para leerlo. */}
          <TableCell
            colSpan={NUM_COLUMNAS}
            className="whitespace-normal bg-muted/30 p-4"
          >
            <div className="max-w-3xl space-y-4">
              <DecisionDetail decision={detalle.data.decision} />
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}
