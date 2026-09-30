import type { components } from '@/api/schema'

type DecisionType = components['schemas']['DecisionType']
type CaseStatus = components['schemas']['CaseStatus']

/**
 * Lo que ve alguien sin contexto del proyecto, no el valor de la base
 * (mejoras2). El valor crudo sigue viajando por la API; esto es sólo texto.
 */
export const ETIQUETA_DECISION: Record<DecisionType, string> = {
  APPROVE: 'Aprobado',
  CHALLENGE: 'Requiere verificación',
  BLOCK: 'Bloqueado',
  ESCALATE_TO_HUMAN: 'Derivado al analista',
}

/** Nombre de las variables CSS de `index.css` (`--decision-<clave>-bg/fg`). */
export const CLAVE_COLOR_DECISION: Record<DecisionType, string> = {
  APPROVE: 'approve',
  CHALLENGE: 'challenge',
  BLOCK: 'block',
  ESCALATE_TO_HUMAN: 'escalate',
}

export const ETIQUETA_ESTADO: Record<CaseStatus, string> = {
  RECEIVED: 'Recibido',
  ANALYZING: 'Analizando',
  DECIDED: 'Decidido',
  PENDING_HUMAN: 'En revisión',
  RESOLVED: 'Resuelto',
  FAILED: 'Falló',
}

/** Estados en los que el caso ya no va a cambiar solo: no hay que seguir
 * consultándolo. `FAILED` nunca tiene decisión, así que "hasta que haya
 * decisión" no alcanza para cortar el sondeo. */
export const ESTADOS_TERMINALES: readonly CaseStatus[] = ['DECIDED', 'PENDING_HUMAN', 'RESOLVED', 'FAILED']
