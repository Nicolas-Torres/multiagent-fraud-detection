import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { api } from '@/api/client'
import { GraphPanel } from '@/components/GraphPanel'
import { ResolutionForm } from '@/components/ResolutionForm'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { decisionVariant, severityVariant } from '@/lib/badges'
import { formatAmount, formatDateTime } from '@/lib/format'

export function CaseDetail() {
  const { caseId } = useParams<{ caseId: string }>()

  const query = useQuery({
    queryKey: ['case', caseId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/cases/{case_id}', {
        params: { path: { case_id: caseId! } },
      })
      if (error) throw error
      return data
    },
    enabled: !!caseId,
    // El caso puede seguir avanzando (RECEIVED → ANALYZING → DECIDED) — la
    // misma razón de polling que la Cola (§4.2, ya decidido: nunca WebSocket).
    refetchInterval: 8_000,
  })

  if (query.isLoading) return <Skeleton className="h-96 w-full" />
  if (query.isError || !query.data) {
    return <p className="text-destructive">No se pudo cargar el caso.</p>
  }

  const caso = query.data
  const { decision, transaction, customer, human_resolution } = caso

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/" className="text-sm text-muted-foreground hover:underline">
            ← Cola
          </Link>
          <h1 className="text-xl font-semibold">Caso {caso.case_id}</h1>
        </div>
        <Badge variant="outline">{caso.status}</Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Transacción</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
          <Field label="Monto" value={formatAmount(transaction.amount, transaction.currency)} />
          <Field label="País" value={transaction.country} />
          <Field label="Canal" value={transaction.channel} />
          <Field label="Comercio" value={transaction.merchant_id} />
          <Field label="Dispositivo" value={transaction.device_id} />
          <Field label="Emisor" value={transaction.issuer_bank ?? '—'} />
          <Field label="Fecha" value={formatDateTime(transaction.timestamp)} />
          <Field label="Cliente" value={transaction.customer_id} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Contexto del cliente</CardTitle>
        </CardHeader>
        <CardContent>
          {customer ? (
            <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
              <Field
                label="Monto habitual"
                value={formatAmount(customer.usual_amount_avg, customer.currency)}
              />
              <Field
                label="Horario habitual"
                value={`${customer.usual_hour_start}–${customer.usual_hour_end} (${customer.timezone})`}
              />
              <Field label="Países habituales" value={customer.usual_countries.join(', ') || 'ninguno'} />
              <Field label="Canal habitual" value={customer.usual_channel} />
              <Field label="Segmento" value={customer.segment} />
              <Field label="Límite diario" value={formatAmount(customer.daily_limit, customer.currency)} />
            </div>
          ) : (
            // Información de fraude, no un hueco vacío — §5 del briefing.
            <p className="text-muted-foreground">Cliente sin perfil previo.</p>
          )}
        </CardContent>
      </Card>

      {decision && (
        <>
          {decision.degraded_agents.length > 0 && (
            <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              Evidencia incompleta: {decision.degraded_agents.join(', ')} no completó su
              análisis. La confianza refleja esta falla, no una señal de fraude.
            </div>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Decisión
                <Badge variant={decisionVariant(decision.decision)}>{decision.decision}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
                <Field label="Confianza" value={decision.confidence.toFixed(2)} />
                {decision.confidence_rationale && (
                  <Field label="Ajuste del árbitro" value={decision.confidence_rationale} wide />
                )}
              </div>

              {decision.signals.length > 0 && (
                <div>
                  <h3 className="mb-2 text-sm font-medium">Señales</h3>
                  <ul className="space-y-1">
                    {decision.signals.map((s) => (
                      <li key={s.code} className="flex items-center gap-2 text-sm">
                        <Badge variant={severityVariant(s.severity)}>{s.severity}</Badge>
                        {s.description}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {decision.citations_internal.length > 0 && (
                <div>
                  <h3 className="mb-2 text-sm font-medium">Políticas citadas</h3>
                  <ul className="space-y-1 text-sm text-muted-foreground">
                    {decision.citations_internal.map((c) => (
                      <li key={c.policy_id}>
                        {c.policy_id} (v{c.version})
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {decision.citations_external.length > 0 && (
                <div>
                  <h3 className="mb-2 text-sm font-medium">Fuentes externas</h3>
                  <ul className="space-y-1 text-sm">
                    {decision.citations_external.map((c) => (
                      <li key={c.url}>
                        <a
                          href={c.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-primary hover:underline"
                        >
                          {c.summary}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-md border p-3">
                  <h3 className="mb-1 text-sm font-medium">A favor de investigar</h3>
                  <p className="text-sm text-muted-foreground">{decision.debate.pro_fraud_argument}</p>
                </div>
                <div className="rounded-md border p-3">
                  <h3 className="mb-1 text-sm font-medium">A favor del cliente</h3>
                  <p className="text-sm text-muted-foreground">{decision.debate.pro_customer_argument}</p>
                </div>
              </div>

              <div>
                <h3 className="mb-1 text-sm font-medium">Explicación de auditoría</h3>
                <p className="text-sm text-muted-foreground">{decision.explanation_audit}</p>
              </div>

              <div>
                {/* Tal como la sirve `CaseDetail` — nunca reconstruida (§5). */}
                <h3 className="mb-1 text-sm font-medium">Explicación al cliente</h3>
                <p className="text-sm text-muted-foreground">{decision.explanation_customer}</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recorrido por el grafo</CardTitle>
            </CardHeader>
            <CardContent>
              <GraphPanel agentRoute={decision.agent_route} degradedAgents={decision.degraded_agents} />
            </CardContent>
          </Card>
        </>
      )}

      {human_resolution ? (
        <Card>
          <CardHeader>
            <CardTitle>Resolución humana</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            <Field label="Acción" value={human_resolution.action} />
            <Field label="Analista" value={human_resolution.analyst_id} />
            {human_resolution.notes && <Field label="Notas" value={human_resolution.notes} wide />}
            <Field label="Resuelto" value={formatDateTime(human_resolution.resolved_at)} />
          </CardContent>
        </Card>
      ) : (
        caso.status === 'PENDING_HUMAN' && <ResolutionForm caseId={caso.case_id} />
      )}
    </div>
  )
}

function Field({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? 'col-span-full' : undefined}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}
