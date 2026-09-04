import { useEffect, useRef, useState } from 'react'

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
  /** El stream emitió `done` -el caso llegó a un estado terminal. */
  done: boolean
}

export function useCaseProgress(caseId: string | null, onDone?: () => void): CaseProgress {
  const [ranNodes, setRanNodes] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const [done, setDone] = useState(false)

  // Última versión de `onDone`, leída dentro del efecto sin ser su
  // dependencia -si lo fuera, una función inline nueva en cada render
  // (el caso típico) reabriría el `EventSource` en cada render, no sólo
  // cuando cambia `caseId`.
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone

  useEffect(() => {
    setRanNodes([])
    setConnected(false)
    setDone(false)
    if (!caseId) return

    const fuente = new EventSource(`/api/v1/cases/${caseId}/stream`)

    fuente.addEventListener('open', () => setConnected(true))
    fuente.addEventListener('node', (evento) => {
      const { node } = JSON.parse((evento as MessageEvent).data) as { node: string }
      setRanNodes((previos) => [...previos, node])
    })
    // `onDone` se dispara acá, en el instante real del evento -no desde un
    // efecto que mire `done` después-: si algo ajeno resetea `caseId` (por
    // ejemplo, el sondeo de "hay algo en ANALYZING" de Dashboard deja de
    // encontrar este caso apenas termina) justo en ese momento, un efecto
    // dependiente de `done` puede cancelarse a mitad de camino por esa
    // razón ajena, y quien esperaba reaccionar al final nunca se entera.
    fuente.addEventListener('done', () => {
      setDone(true)
      onDoneRef.current?.()
      fuente.close()
    })
    fuente.onerror = () => setConnected(false)

    return () => fuente.close()
  }, [caseId])

  return { ranNodes, connected, done }
}
