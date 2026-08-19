import { useEffect, useState } from 'react'

/**
 * Progreso real del grafo (ADR-0018), por SSE nativo — sin librería nueva.
 * `EventSource` reconecta solo ante un corte de red; acá sólo se refleja
 * si está conectado en este instante, nunca se reintenta a mano.
 *
 * Puramente un agregado visual: si el stream nunca conecta o se corta a
 * mitad de camino, el caso igual termina por el polling que ya existe
 * (`Home.tsx`) — este hook no es la fuente de verdad del veredicto.
 */
export interface CaseProgress {
  ranNodes: string[]
  connected: boolean
}

export function useCaseProgress(caseId: string | null): CaseProgress {
  const [ranNodes, setRanNodes] = useState<string[]>([])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    setRanNodes([])
    setConnected(false)
    if (!caseId) return

    const fuente = new EventSource(`/api/v1/cases/${caseId}/stream`)

    fuente.addEventListener('open', () => setConnected(true))
    fuente.addEventListener('node', (evento) => {
      const { node } = JSON.parse((evento as MessageEvent).data) as { node: string }
      setRanNodes((previos) => [...previos, node])
    })
    fuente.addEventListener('done', () => fuente.close())
    fuente.onerror = () => setConnected(false)

    return () => fuente.close()
  }, [caseId])

  return { ranNodes, connected }
}
