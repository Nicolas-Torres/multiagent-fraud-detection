import type { components } from '@/api/schema'
import { Field } from '@/components/Field'
import { GraphPanel } from '@/components/GraphPanel'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { decisionVariant, severityVariant } from '@/lib/badges'

type DecisionRead = components['schemas']['DecisionRead']

/**
 * El debate, las señales, las citas y el recorrido por el grafo — el
 * núcleo "vistoso" de un caso decidido. Compartido entre `CaseDetail`
 * (el detalle completo, con transacción/cliente/resolución alrededor) y
 * `Home` (el panel fijo de la vitrina, donde es lo único que se muestra).
 */
export function DecisionShowcase({ decision }: { decision: DecisionRead }) {
  return (
    <>
      {decision.degraded_agents.length > 0 && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          Evidencia incompleta: {decision.degraded_agents.join(', ')} no completó su
          análisis. La confianza refleja esta falla, no una señal de fraude.
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Recorrido por el grafo</CardTitle>
        </CardHeader>
        <CardContent>
          <GraphPanel agentRoute={decision.agent_route} degradedAgents={decision.degraded_agents} />
        </CardContent>
      </Card>

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

          <SellosAuditoria decision={decision} />

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


    </>
  )
}

const SELLOS: { key: keyof DecisionRead; label: string }[] = [
  { key: 'scoring_version', label: 'Fórmula de riesgo' },
  { key: 'policy_catalog_version', label: 'Catálogo de políticas' },
  { key: 'retrieval_index_version', label: 'Índice de recuperación' },
  { key: 'explanation_prompt_version', label: 'Prompt de explicación' },
  { key: 'threat_intel_version', label: 'Snapshot de inteligencia externa' },
]

/**
 * La misma información que ya viaja al final de `explanation_audit`
 * —ruta de agentes y los cinco sellos de versión (contrato §2.5)—, pero
 * como campos tipados en vez de una oración corrida. `explanation_audit`
 * sigue mostrándose completo abajo: nada se oculta, esto sólo lo hace
 * legible de un vistazo antes del párrafo de auditoría.
 */
function SellosAuditoria({ decision }: { decision: DecisionRead }) {
  const presentes = SELLOS.filter((s) => decision[s.key] != null)
  if (presentes.length === 0) return null

  return (
    <div>
      <h3 className="mb-2 text-sm font-medium">Sellos de auditoría</h3>
      <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
        {presentes.map((s) => (
          <Field key={s.key} label={s.label} value={String(decision[s.key])} />
        ))}
      </div>
    </div>
  )
}
