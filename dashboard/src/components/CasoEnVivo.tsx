import type { ReactNode } from 'react'

import type { components } from '@/api/schema'
import { DecisionBadge } from '@/components/DecisionBadge'
import { Field } from '@/components/Field'
import { GraphPanel } from '@/components/GraphPanel'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ETIQUETA_DECISION, ETIQUETA_ESTADO } from '@/lib/etiquetas'
import { formatAmount, formatDateTime, formatTransactionId } from '@/lib/format'

type CaseDetail = components['schemas']['CaseDetail']

/**
 * Qué está haciendo el grafo, según el último nodo que terminó (SSE,
 * ADR-0018). Antes rotaba frases cada 2.5 s sin mirar el progreso real y
 * podía decir "leyendo el contexto" con el debate ya corriendo (mejoras2).
 * Se evalúa de la etapa más avanzada a la más temprana: la primera cuyos
 * nodos terminaron todos manda.
 */
// Cortas a propósito: tienen que entrar en un renglón a 390 px, para que la
// descripción no cambie de alto y mueva el grafo.
const ETAPAS: [string[], string][] = [
  [['explainability'], 'Guardando la decisión…'],
  [['decision_arbiter'], 'Redactando la explicación al cliente…'],
  [['debate_pro_fraud', 'debate_pro_customer'], 'El árbitro está decidiendo…'],
  [['evidence_aggregation'], 'Debate a favor y en contra del fraude…'],
  [['internal_policy_rag'], 'Consolidando la evidencia y el riesgo…'],
  [
    ['transaction_context', 'behavioral_pattern', 'external_threat_intel'],
    'Buscando las políticas que aplican…',
  ],
]

export function fraseDelProgreso(ranNodes: string[], connected: boolean): string {
  if (!connected) return 'Conectando con el análisis en vivo…'
  const hechos = new Set(ranNodes)
  const etapa = ETAPAS.find(([nodos]) => nodos.every((n) => hechos.has(n)))
  return etapa?.[1] ?? 'Revisando contexto, historial e intel…'
}

/**
 * La tarjeta del grafo de Transactions, **siempre en el mismo lugar**: antes
 * el grafo vivía dentro del panel "Analizando…" y se desplazaba con él.
 * Un solo `GraphPanel` que cambia de props, nunca dos alternados: React Flow
 * se desmontaba y se pintaba vacío hasta su `fitView`.
 */
export function TarjetaGrafo({
  caso,
  ranNodes,
  connected,
  chips,
}: {
  caso: CaseDetail
  ranNodes: string[]
  connected: boolean
  /** Los casos en curso, en el encabezado (mejoras2): arriba del grafo
   * desplazaban la tarjeta. */
  chips?: ReactNode
}) {
  const decision = caso.decision
  return (
    <Card>
      <CardHeader className="max-md:gap-1">
        {/* `min-h-8`: la altura de un chip. Sin esto, el primer chip agranda
            el encabezado y empuja el grafo unos píxeles al ejecutar. */}
        <div className="flex min-h-8 flex-wrap items-center gap-2">
          <CardTitle>Recorrido por el grafo</CardTitle>
          {chips}
        </div>
        {/* Siempre dos renglones, de uno cada uno: si la descripción cambiara
            de alto entre "analizando" y "decidido", el grafo se movería
            (mejoras2: grafo estático). */}
        <CardDescription>
          <span className="block truncate">
            {formatTransactionId(caso.transaction.transaction_id)} · {caso.transaction.customer_id} —{' '}
            {ETIQUETA_ESTADO[caso.status]}
          </span>
          <span className="block truncate">
            {decision
              ? `Resultado: ${ETIQUETA_DECISION[decision.decision]}`
              : fraseDelProgreso(ranNodes, connected)}
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent className="max-md:px-0">
        <GraphPanel
          agentRoute={decision ? decision.agent_route : connected ? ranNodes : []}
          degradedAgents={decision ? decision.degraded_agents : []}
          caseDecided={!!decision}
          animating={!decision && !connected}
        />
      </CardContent>
    </Card>
  )
}

/**
 * Sólo en mobile (mejoras2): los datos que la tabla oculta por ancho. Sin
 * esto, quien ejecuta una transacción desde el celular ve el grafo moverse
 * pero no sabe qué transacción es. En desktop no se muestra: las columnas
 * están en la tabla. Usa el mismo corte `@3xl` que oculta esas columnas.
 */
export function DatosDelCasoMobile({ caso }: { caso: CaseDetail }) {
  const t = caso.transaction
  return (
    <Card className="@3xl:hidden">
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <Field label="Tx ID" value={formatTransactionId(t.transaction_id)} />
          <Field label="Cliente" value={t.customer_id} />
          <Field label="Monto" value={formatAmount(String(t.amount), t.currency)} />
          <Field label="Canal" value={t.channel.toUpperCase()} />
          <Field label="País" value={t.country} />
          <Field label="Banco" value={t.issuer_bank ?? '—'} />
          <Field label="Fecha" value={formatDateTime(t.timestamp)} wide />
          <Field label="Estado" value={ETIQUETA_ESTADO[caso.status]} />
          {caso.decision && (
            <div>
              <dt className="text-xs text-muted-foreground">Decisión</dt>
              <dd>
                <DecisionBadge decision={caso.decision.decision} compacto />
              </dd>
            </div>
          )}
        </dl>
      </CardContent>
    </Card>
  )
}
