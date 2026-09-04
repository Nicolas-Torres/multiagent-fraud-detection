import { useEffect, useState } from 'react'

import { GraphPanel } from '@/components/GraphPanel'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

// Acompañan al progreso real (ADR-0018), no lo reemplazan: el stream dice
// qué nodo terminó, pero no narra qué está haciendo mientras corre. Van en
// el orden típico de un superstep a otro, nada más.
const FRASES = [
  'Leyendo el contexto de la transacción...',
  'Comparando contra el comportamiento habitual del cliente...',
  'Consultando inteligencia externa sobre el emisor...',
  'Recuperando políticas relacionadas por similitud...',
  'Armando el debate pro-fraude y pro-cliente...',
  'El árbitro con LLM está evaluando el veredicto...',
]
const INTERVALO_MS = 2_500

interface AnalyzingPanelProps {
  /** Transacción · cliente del caso que este panel sigue — con más de una
   * ejecución en curso a la vez, cada tarjeta necesita decir cuál es la
   * suya; sin esto, "Analizando…" es indistinguible entre casos. */
  identificador: string
  status: string
  ranNodes: string[]
  connected: boolean
}

export function AnalyzingPanel({ identificador, status, ranNodes, connected }: AnalyzingPanelProps) {
  const [frase, setFrase] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setFrase((f) => (f + 1) % FRASES.length), INTERVALO_MS)
    return () => clearInterval(id)
  }, [])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Analizando…</CardTitle>
        <CardDescription>{identificador}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="mb-2 text-sm text-muted-foreground">
          Estado: {status}. {FRASES[frase]}
        </p>
        <p className="mb-4 text-xs text-muted-foreground">
          Entre 10 y 20 segundos — son llamadas reales a los proveedores, no una
          simulación. {connected
            ? 'Cada nodo se ilumina apenas termina, en vivo (SSE).'
            : 'Conectando el progreso en vivo — el barrido de abajo sólo marca que el proceso sigue corriendo.'}
        </p>
        {connected ? (
          <GraphPanel agentRoute={ranNodes} degradedAgents={[]} caseDecided={false} />
        ) : (
          <GraphPanel agentRoute={[]} degradedAgents={[]} animating />
        )}
      </CardContent>
    </Card>
  )
}
