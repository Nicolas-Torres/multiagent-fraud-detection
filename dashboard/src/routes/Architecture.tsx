import { useState } from 'react'

import { GraphPanel } from '@/components/GraphPanel'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const GITHUB_ADR_BASE =
  'https://github.com/Nicolas-Torres/multiagent-fraud-detection/blob/main/docs/adr/'

interface AdrHighlight {
  numero: string
  pregunta: string
  respuesta: string
  archivo: string
}

// Cuatro de 17 ADRs, elegidos por la narrativa "¿por qué no...?" — no un
// resumen de los 17. El resto queda a un clic para quien quiera profundizar.
const ADR_HIGHLIGHTS: AdrHighlight[] = [
  {
    numero: 'ADR-0011',
    pregunta: '¿Por qué no dejar que la búsqueda vectorial produzca las citas?',
    respuesta:
      'Porque puede citar con total confianza tres políticas plausibles y equivocadas mientras la decisión correcta sale igual — sin lanzar ningún error. La cita que autoriza un veredicto se resuelve por identidad (qué política realmente disparó); la búsqueda por similitud sólo aporta contexto relacionado, nunca autoriza nada.',
    archivo: '0011-citacion-por-identidad-descubrimiento-por-similitud.md',
  },
  {
    numero: 'ADR-0004',
    pregunta: '¿Por qué no consultar el historial del cliente de la forma normal?',
    respuesta:
      'Porque el bug es invisible en producción —el futuro no puede filtrarse en una tabla que todavía no lo tiene— y sólo aparece como métricas sospechosamente buenas en la evaluación. Toda consulta de historial se filtra por el timestamp de la transacción bajo análisis, nunca por el reloj real.',
    archivo: '0004-consultas-de-historial-as-of.md',
  },
  {
    numero: 'ADR-0016',
    pregunta: '¿Por qué no darle al árbitro con LLM poder de veto completo?',
    respuesta:
      '"El modelo lo consideró razonable" no es una respuesta que un regulador acepta. El árbitro puede escalar el piso determinista con justificación, nunca bajarlo — la cautela mínima del catálogo queda estructuralmente fuera del alcance del LLM.',
    archivo: '0016-el-arbitro-con-llm-escala-pero-no-cruza-el-piso-determinista.md',
  },
  {
    numero: 'ADR-0006',
    pregunta: '¿Por qué no hacer los nueve agentes con LLM, como sugiere el enunciado?',
    respuesta:
      'Porque preguntarle a un LLM si 4500 es mayor que 3600 es la herramienta menos confiable disponible para la operación más simple posible. Tres agentes "sensores" son deterministas a propósito; el LLM entra donde vive la ambigüedad real: el juicio, no la aritmética.',
    archivo: '0006-reparto-deterministico-y-llm.md',
  },
]

function DiagramaC4() {
  const [falta, setFalta] = useState(false)

  if (falta) {
    return (
      <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
        Diagrama C4 pendiente de exportar — ver <code>docs/diagrams/c4-container.drawio</code>.
      </div>
    )
  }

  return (
    <img
      src="/c4-container.png"
      alt="Diagrama de contenedores C4 del sistema"
      className="w-full rounded-md border"
      onError={() => setFalta(true)}
    />
  )
}

export function Architecture() {
  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-2xl font-semibold">Cómo se construyó</h1>
        <p className="text-muted-foreground">
          Diecisiete decisiones de diseño respaldan este sistema. Estas cuatro son las
          que mejor explican por qué el resultado se ve como se ve.
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Arquitectura de contenedores</h2>
        <DiagramaC4 />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">El grafo de agentes</h2>
        <p className="text-sm text-muted-foreground">
          La misma topología que corre en cada caso real — nueve nodos, tres
          supersteps paralelos, sin dibujar a mano.
        </p>
        <GraphPanel agentRoute={[]} degradedAgents={[]} />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Decisiones de diseño</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {ADR_HIGHLIGHTS.map((adr) => (
            <Card key={adr.numero}>
              <CardHeader>
                <CardTitle className="text-base">{adr.pregunta}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-muted-foreground">{adr.respuesta}</p>
                <a
                  href={`${GITHUB_ADR_BASE}${adr.archivo}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-primary hover:underline"
                >
                  {adr.numero} completo →
                </a>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
    </div>
  )
}
