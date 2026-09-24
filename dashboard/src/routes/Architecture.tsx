import { useState } from 'react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const GITHUB_DOCS_BASE =
  'https://github.com/Nicolas-Torres/multiagent-fraud-detection/blob/main/docs/'

interface DecisionDestacada {
  fuente: string
  pregunta: string
  respuesta: string
  archivo: string
}

// Cuatro de las 24 decisiones, elegidas como las preguntas que haría un
// líder técnico al revisar el sistema — no un resumen de los ADR. El resto
// queda a un clic para quien quiera profundizar.
const DECISIONES: DecisionDestacada[] = [
  {
    fuente: 'ADR-0006',
    pregunta: '¿Por qué no hacer los nueve agentes con LLM?',
    respuesta:
      'Porque preguntarle a un LLM si 4500 es mayor que 3600 es la herramienta menos confiable disponible para la operación más simple posible. Tres agentes "sensores" son deterministas a propósito; el LLM entra donde vive la ambigüedad real: el juicio, no la aritmética.',
    archivo: 'adr/0006-reparto-deterministico-y-llm.md',
  },
  {
    fuente: 'ADR-0011',
    pregunta: '¿Cómo se evita que el RAG cite una política que no aplicó?',
    respuesta:
      'La cita que respalda un veredicto no sale de la búsqueda vectorial: se resuelve por identidad, desde la política que realmente disparó. La similitud sólo agrega políticas relacionadas como contexto. Así el sistema no puede justificar una decisión con una norma que no evaluó.',
    archivo: 'adr/0011-citacion-por-identidad-descubrimiento-por-similitud.md',
  },
  {
    fuente: 'ADR-0016',
    pregunta: '¿Qué impide que el LLM apruebe algo que las reglas ya bloquearon?',
    respuesta:
      'Las reglas fijan un veredicto mínimo y el árbitro con LLM sólo puede subirlo, nunca bajarlo. Si lo intenta, el caso falla en vez de guardarse. El peor error posible del modelo es escalar de más, no aprobar de menos.',
    archivo: 'adr/0016-el-arbitro-con-llm-escala-pero-no-cruza-el-piso-determinista.md',
  },
  {
    fuente: 'Acta 03',
    pregunta: '¿Qué pasa si el proveedor de IA se cae a mitad de un caso?',
    respuesta:
      'Cada agente de evidencia degrada solo, sin arrastrar a sus hermanos. Si fallan los embeddings, las citas obligatorias sobreviven igual. Si falla el árbitro, el caso se escala a un humano. El sistema dice "evidencia incompleta" en vez de inventar.',
    archivo: 'reviews/03-grafo-y-persistencia.md',
  },
]

function DiagramaC4() {
  const [falta, setFalta] = useState(false)

  if (falta) {
    return (
      <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
        Diagrama C4 pendiente de exportar — ver <code>docs/diagrams/likec4/c4-container.c4</code>.
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
      <p className="text-muted-foreground">
        Veinticuatro decisiones de diseño respaldan este sistema. Estas cuatro son
        las que mejor explican por qué el resultado se ve como se ve.
      </p>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Arquitectura de contenedores</h2>
        <DiagramaC4 />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Decisiones de diseño</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {DECISIONES.map((d) => (
            <Card key={d.archivo}>
              <CardHeader>
                <CardTitle className="text-base">{d.pregunta}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-muted-foreground">{d.respuesta}</p>
                <a
                  href={`${GITHUB_DOCS_BASE}${d.archivo}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-primary hover:underline"
                >
                  Ver {d.fuente} →
                </a>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
    </div>
  )
}
