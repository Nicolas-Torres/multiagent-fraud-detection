import { useState } from 'react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

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

const RECORRIDO: string[] = [
  'Llega la transacción: la API responde 202 y el análisis corre en segundo plano.',
  'Tres sensores en paralelo, con reglas: contexto, comportamiento e inteligencia externa.',
  'RAG de políticas: cita las que dispararon y busca otras relacionadas.',
  'Agregación: puntaje de riesgo y confianza, sin LLM.',
  'Debate: dos agentes LLM argumentan a favor y en contra, en paralelo.',
  'Árbitro: el LLM decide sin bajar el piso de las reglas; se redacta la explicación y se sellan las versiones usadas.',
  'Si el veredicto es escalar, el caso entra a la cola Human-in-the-loop.',
]

const EVALUACION: { que: string; metodo: string; resultado: string }[] = [
  {
    que: 'Motor de reglas',
    metodo: 'Match exacto contra el ground truth, como gate de CI',
    resultado: '7000/7000',
  },
  {
    que: 'Recuperación semántica (ablación)',
    metodo: 'recall@1 y MRR sobre las 653 transacciones con política esperada',
    resultado: '0.79 / 0.88',
  },
  {
    que: 'Razonamiento de los agentes',
    metodo: 'LLM-as-judge (DeepEval) sobre un golden set curado',
    resultado: 'Se vigila por tendencia; nunca bloquea el CI',
  },
]

const TECNOLOGIAS: { nombre: string; uso: string }[] = [
  { nombre: 'Python + FastAPI', uso: 'API async: ingesta de casos, progreso en vivo por SSE, cola HITL' },
  { nombre: 'LangGraph', uso: 'Orquestación del grafo de 10 nodos con ramas en paralelo' },
  {
    nombre: 'Claude Sonnet 5 (Anthropic)',
    uso: 'Debate, árbitro con salida estructurada y explicación al cliente',
  },
  { nombre: 'Claude Haiku + web search', uso: 'Recolección semanal de inteligencia externa, en build, no en cada caso' },
  { nombre: 'Gemini Embedding 2', uso: 'Índice vectorial de las políticas para el RAG' },
  {
    nombre: 'PostgreSQL + pgvector (Neon)',
    uso: 'Datos, índice vectorial y sellos de auditoría en una sola base',
  },
  { nombre: 'SQLAlchemy 2 + Alembic', uso: 'ORM async y migraciones versionadas' },
  { nombre: 'DeepEval', uso: 'LLM-as-judge sobre un golden set curado' },
  { nombre: 'LangSmith', uso: 'Trazas, costo y latencia por nodo (alimenta este dashboard)' },
  { nombre: 'OpenTelemetry + Grafana', uso: 'Trazas, logs y métricas de infraestructura' },
  { nombre: 'React + TypeScript + React Flow', uso: 'Este dashboard y el grafo en vivo' },
  {
    nombre: 'Docker + GitHub Actions',
    uso: 'Imagen única y CI con gates (tests, 7000/7000, migraciones)',
  },
  { nombre: 'Terraform', uso: 'Infraestructura como código en Azure y GCP' },
  { nombre: 'Azure Container Apps + GCP Cloud Run', uso: 'Despliegue en dos nubes' },
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
        <h2 className="text-lg font-semibold">Recorrido de una transacción</h2>
        <ol className="list-decimal space-y-1.5 pl-5 text-sm text-muted-foreground marker:text-foreground">
          {RECORRIDO.map((paso) => (
            <li key={paso}>{paso}</li>
          ))}
        </ol>
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

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Cómo se evalúa</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Qué se mide</TableHead>
              <TableHead>Método</TableHead>
              <TableHead>Resultado</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {EVALUACION.map((e) => (
              <TableRow key={e.que}>
                <TableCell className="whitespace-normal font-medium">{e.que}</TableCell>
                <TableCell className="whitespace-normal text-muted-foreground">{e.metodo}</TableCell>
                <TableCell className="whitespace-normal">{e.resultado}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Tecnologías</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tecnología</TableHead>
              <TableHead>Dónde se usa</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {TECNOLOGIAS.map((t) => (
              <TableRow key={t.nombre}>
                <TableCell className="whitespace-normal font-medium">{t.nombre}</TableCell>
                <TableCell className="whitespace-normal text-muted-foreground">{t.uso}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
    </div>
  )
}
