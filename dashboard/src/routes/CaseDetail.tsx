import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { api } from '@/api/client'
import { DecisionShowcase } from '@/components/DecisionShowcase'
import { Field } from '@/components/Field'
import { ResolutionForm } from '@/components/ResolutionForm'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
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
          <Link to="/queue" className="text-sm text-muted-foreground hover:underline">
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

      {decision && <DecisionShowcase decision={decision} />}

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
