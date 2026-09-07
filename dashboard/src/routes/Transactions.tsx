import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDownIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

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

// Sin `case_id`: ese campo se resuelve en vivo con GET /cases/showcase
// (contrato §2.3), nunca horneado en el build — ver el docstring de
// scripts/seed_showcase.py y docs/reviews/11-ci-cd-azure.md §2.2/§6.1.
interface ShowcaseCase {
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
  const [errorEjecucion, setErrorEjecucion] = useState<string | null>(null)
  const [ultimasCorridas, setUltimasCorridas] = useState<Record<string, number>>(leerUltimasCorridas)
  // Sólo para las filas en vivo/diversas: no tienen `case_id` hasta el
  // primer "Ejecutar" — una vez que lo tienen, esta fila puede consultar y
  // mostrar su propia "Decisión del LLM" igual que una de vitrina.
  const [caseIdPorEscenario, setCaseIdPorEscenario] =
    useState<Record<string, string>>(leerCaseIdsPorEscenario)
  // Casos que este tab disparó y todavía ocupan un chip en la tira -no
  // sólo "corriendo": un chip ya decidido se queda un rato ahí (ver
  // `ChipEnCurso`) hasta que se lo mira o se cierra solo.
  const [casosEnCurso, setCasosEnCurso] = useState<string[]>([])
  // Cuál de esos chips maneja el panel destacado ahora mismo -`null` es el
  // caso de vitrina (`casoInicial`), nunca un chip vacío.
  const [chipSeleccionado, setChipSeleccionado] = useState<string | null>(null)
  const [ahora, setAhora] = useState(() => Date.now())
  const queryClient = useQueryClient()

  // Los `case_id` reales de la vitrina, resueltos en vivo (contrato §2.3) —
  // nunca los del JSON horneado en el build. Un entorno recién desplegado
  // que todavía no corrió el seed de vitrina devuelve menos de 5 ítems: esas
  // filas simplemente muestran "—" (ver `FilaTransaccion`), no rompen nada.
  const vitrinaQuery = useQuery({
    queryKey: ['cases-showcase'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/cases/showcase')
      if (error) throw error
      return data
    },
  })
  const vitrinaCaseIds: Record<string, string> = {}
  for (const item of vitrinaQuery.data ?? []) {
    vitrinaCaseIds[item.transaction_id] = item.case_id
  }

  useEffect(() => {
    const id = setInterval(() => setAhora(Date.now()), 1_000)
    return () => clearInterval(id)
  }, [])

  // Selecciona `caseId` para el panel destacado. Si el chip que se abandona
  // ya tiene veredicto, se cierra en el mismo gesto -ya cumplió su función
  // (mostrar el resultado) y no hace falta mantenerlo ocupando la tira. Si
  // todavía está corriendo, sigue en segundo plano sin seleccionar, y
  // `ChipEnCurso` se encarga de cerrarlo solo cuando le toque.
  function seleccionar(caseId: string) {
    if (chipSeleccionado && chipSeleccionado !== caseId) {
      const anterior = queryClient.getQueryData<CaseDetailType>(['case', chipSeleccionado])
      if (anterior?.decision) {
        setCasosEnCurso((previos) => previos.filter((id) => id !== chipSeleccionado))
      }
    }
    setChipSeleccionado(caseId)
  }

  function quitarChip(caseId: string) {
    setCasosEnCurso((previos) => previos.filter((id) => id !== caseId))
  }

  // El desafiado (CHALLENGE) es el más representativo para el primer
  // vistazo: tiene señal, cita, debate y confianza intermedia — el resto
  // queda a un click en la tabla de abajo. `null` hasta que `vitrinaQuery`
  // resuelva (o si este entorno todavía no sembró ese caso en particular).
  const casoInicial =
    vitrinaCaseIds[showcaseCases[1]?.transaction_id ?? ''] ??
    vitrinaCaseIds[showcaseCases[0]?.transaction_id ?? ''] ??
    null

  // Panel destacado: el chip elegido, o -por default, nada seleccionado- el
  // caso curado de vitrina, ya decidido. Es la primera prueba real que ve
  // alguien que entra sin ejecutar nada.
  const panelCaseId = chipSeleccionado ?? casoInicial
  const panelDetalle = useQuery({
    queryKey: ['case', panelCaseId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/cases/{case_id}', {
        params: { path: { case_id: panelCaseId! } },
      })
      if (error) throw error
      return data
    },
    enabled: !!panelCaseId,
    refetchInterval: (query) => (query.state.data?.decision ? false : 3_000),
  })
  const progreso = useCaseProgress(
    chipSeleccionado && !panelDetalle.data?.decision ? chipSeleccionado : null,
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
      setCasosEnCurso((previos) => [...previos, data.case_id])
      seleccionar(data.case_id)
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
      {casosEnCurso.length > 0 && (
        <section className="flex flex-wrap gap-2">
          {casosEnCurso.map((caseId) => (
            <ChipEnCurso
              key={caseId}
              caseId={caseId}
              seleccionado={chipSeleccionado === caseId}
              onSeleccionar={() => seleccionar(caseId)}
              onQuitar={() => quitarChip(caseId)}
            />
          ))}
        </section>
      )}

      {/* Panel destacado: ver comentario junto a `panelCaseId` arriba. */}
      <section>
        {panelDetalle.isLoading && <Skeleton className="h-96 w-full" />}
        {panelDetalle.isError && <p className="text-destructive">No se pudo cargar el caso.</p>}
        {panelDetalle.data && !panelDetalle.data.decision && (
          <AnalyzingPanel
            identificador={`${formatTransactionId(panelDetalle.data.transaction.transaction_id)} · ${panelDetalle.data.transaction.customer_id}`}
            status={panelDetalle.data.status}
            ranNodes={progreso.ranNodes}
            connected={progreso.connected}
          />
        )}
        {panelDetalle.data?.decision && <GraphSection decision={panelDetalle.data.decision} />}
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
                key={item.id}
                claveEscenario={item.id}
                transactionId={item.transaction_id}
                payload={item.payload}
                caseId={vitrinaCaseIds[item.transaction_id] ?? null}
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

  // Misma `queryKey` que usan `ChipEnCurso` y el panel destacado para este
  // mismo caso mientras está en la tira -React Query la deduplica, cero
  // costo de red extra. El propio `refetchInterval` es necesario igual: en
  // cuanto el chip se cierra (`casosEnCurso`), esta fila queda como la
  // única observadora — sin esto, se congelaría mostrando "ANALYZING" para
  // siempre.
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
    refetchInterval: (query) => (query.state.data?.decision ? false : 3_000),
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

// Cuánto se queda un chip ya decidido, sin seleccionar, antes de cerrarse
// solo -deja libre la tira sin que el usuario tenga que hacer nada, pero da
// un momento para notarlo si justo estaba mirando la tabla.
const COOLDOWN_CHIP_MS = 5_000

/**
 * Un chip por caso en curso -el grafo en vivo lo muestra el panel destacado
 * de arriba sólo para el que está seleccionado (una sola conexión SSE a la
 * vez, no una por chip); este componente sólo necesita saber si ya terminó,
 * para su propio ciclo de vida.
 */
function ChipEnCurso({
  caseId,
  seleccionado,
  onSeleccionar,
  onQuitar,
}: {
  caseId: string
  seleccionado: boolean
  onSeleccionar: () => void
  onQuitar: () => void
}) {
  // Misma `queryKey` que ya pollean el panel destacado (si este chip está
  // seleccionado) y la fila de abajo -React Query la deduplica.
  const detalle = useQuery({
    queryKey: ['case', caseId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/cases/{case_id}', {
        params: { path: { case_id: caseId } },
      })
      if (error) throw error
      return data as CaseDetailType
    },
    refetchInterval: (query) => (query.state.data?.decision ? false : 3_000),
  })
  const decidido = !!detalle.data?.decision

  // `Transactions` re-renderiza cada 1s (cuenta regresiva del cooldown de
  // las filas) y le pasa a este componente una función `onQuitar` nueva en
  // cada una -si fuera dependencia directa del efecto, el timeout se
  // reiniciaría cada segundo y nunca llegaría a los 5000ms. La última
  // versión se lee desde el ref, sin integrar el efecto.
  const onQuitarRef = useRef(onQuitar)
  onQuitarRef.current = onQuitar

  // Sólo corre para un chip decidido y sin seleccionar: el seleccionado se
  // cierra por el gesto de elegir otro (`seleccionar`, en `Transactions`),
  // nunca por este cooldown -si el usuario lo está mirando, no debería
  // desaparecer solo bajo su cursor.
  useEffect(() => {
    if (!decidido || seleccionado) return
    const id = setTimeout(() => onQuitarRef.current(), COOLDOWN_CHIP_MS)
    return () => clearTimeout(id)
  }, [decidido, seleccionado])

  return (
    <Button
      className="cursor-pointer"
      size="sm"
      variant={seleccionado ? 'default' : 'outline'}
      onClick={onSeleccionar}
    >
      <span className="relative flex size-2">
        {!decidido && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-75" />
        )}
        <span
          className={cn(
            'relative inline-flex size-2 rounded-full',
            decidido ? 'bg-muted-foreground/50' : 'bg-emerald-500',
          )}
        />
      </span>
      {detalle.data
        ? `${formatTransactionId(detalle.data.transaction.transaction_id)} · ${detalle.data.transaction.customer_id}`
        : '…'}
    </Button>
  )
}
