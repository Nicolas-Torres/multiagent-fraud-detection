import { useEffect, useState } from 'react'

import { GraphPanel } from '@/components/GraphPanel'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// Puramente ilustrativas — no reflejan en qué nodo está el grafo de verdad.
// No hay forma honesta de saberlo desde el cliente: W2 escribe todo en un
// solo commit al terminar, sin estados intermedios persistidos (§7.3 del
// contrato). Van en el orden típico de un superstep a otro, nada más.
const FRASES = [
  'Leyendo el contexto de la transacción...',
  'Comparando contra el comportamiento habitual del cliente...',
  'Consultando inteligencia externa sobre el emisor...',
  'Recuperando políticas relacionadas por similitud...',
  'Armando el debate pro-fraude y pro-cliente...',
  'El árbitro con LLM está evaluando el veredicto...',
]
const INTERVALO_MS = 2_500

export function AnalyzingPanel({ status }: { status: string }) {
  const [frase, setFrase] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setFrase((f) => (f + 1) % FRASES.length), INTERVALO_MS)
    return () => clearInterval(id)
  }, [])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Analizando…</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-2 text-sm text-muted-foreground">
          Estado: {status}. {FRASES[frase]}
        </p>
        <p className="mb-4 text-xs text-muted-foreground">
          Entre 10 y 20 segundos — son llamadas reales a los proveedores, no una
          simulación. El barrido de abajo marca que el proceso sigue vivo; el
          sistema no expone qué nodo está corriendo en cada instante porque
          escribe el resultado completo recién al terminar, nunca en partes.
        </p>
        <GraphPanel agentRoute={[]} degradedAgents={[]} animating />
      </CardContent>
    </Card>
  )
}
