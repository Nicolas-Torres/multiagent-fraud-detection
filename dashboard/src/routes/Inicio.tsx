import { ArrowRightIcon } from 'lucide-react'
import { Link } from 'react-router-dom'

import { buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { RecorridoTransaccion } from '@/routes/Architecture'

const ACCESOS = [
  {
    to: '/transactions',
    titulo: 'Probar una transacción',
    texto: 'Ejecuta un escenario y mira cómo el grafo de agentes lo analiza en vivo, nodo por nodo.',
  },
  {
    to: '/queue',
    titulo: 'Revisión humana',
    texto: 'Los casos que el sistema no decide solo y deriva a un analista para que los resuelva.',
  },
  {
    to: '/architecture',
    titulo: 'Cómo se construyó',
    texto: 'La arquitectura, cómo se evalúa, las tecnologías y las decisiones de diseño.',
  },
]

/**
 * Página de entrada (mejoras2): quien llega desde un link no tiene contexto,
 * y el Dashboard muestra números sin decir de qué. Acá, en una pantalla: qué
 * resuelve el sistema, cómo recorre una transacción y por dónde seguir.
 */
export function Inicio() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <section className="space-y-3">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
          Detección de fraude con agentes de IA
        </h2>
        <p className="text-muted-foreground">
          Cada transacción pasa por reglas determinísticas, una búsqueda de las políticas que
          aplican y un debate entre agentes LLM. Las reglas fijan el veredicto mínimo: el LLM
          puede volverlo más estricto, nunca más permisivo, y cada decisión queda sellada para
          auditoría.
        </p>
        <Link to="/transactions" className={cn(buttonVariants({ size: 'lg' }), 'gap-2')}>
          Probar una transacción
          <ArrowRightIcon className="size-4" />
        </Link>
        <p className="text-xs text-muted-foreground">
          Demo pública: las transacciones vienen de un dataset sintético, pero cada análisis llama a
          modelos reales (Claude y Gemini).
        </p>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Recorrido de una transacción</CardTitle>
        </CardHeader>
        <CardContent>
          <RecorridoTransaccion />
        </CardContent>
      </Card>

      <section className="grid gap-4 md:grid-cols-3">
        {ACCESOS.map((a) => (
          <Link key={a.to} to={a.to} className="group">
            <Card className="h-full transition-colors group-hover:bg-muted/50">
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2 text-base">
                  {a.titulo}
                  <ArrowRightIcon className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                </CardTitle>
                <CardDescription>{a.texto}</CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </section>


    </div>
  )
}
