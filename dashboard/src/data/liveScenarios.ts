import type { components } from '@/api/schema'

type TransactionIn = components['schemas']['TransactionIn']

/**
 * Tres de las cinco transacciones reales de la vitrina (`showcase_cases.json`),
 * reutilizadas como plantilla para "ejecutar en vivo": mismos datos reales,
 * corridos de nuevo con un `transaction_id` fresco cada vez que alguien hace
 * clic, para que el visitante vea el pipeline pensar en tiempo real en vez
 * de sólo mirar un resultado ya calculado.
 *
 * El horario importa: el motor evalúa la hora **local** de cada cliente
 * (contrato §2.5), no la hora real en la que alguien clickea el botón — por
 * eso el `timestamp` queda fijo en vez de recalcularse a "ahora". Es el
 * mismo principio que ADR-0004 (as-of, nunca `now()`), aplicado acá para
 * que el escenario siga siendo válido sin importar cuándo se ejecute.
 */
export interface LiveScenario {
  id: string
  label: string
  description: string
  payload: Omit<TransactionIn, 'transaction_id'>
}

export const LIVE_SCENARIOS: LiveScenario[] = [
  {
    id: 'approve',
    label: 'Aprobación limpia',
    description: 'Monto y horario dentro de lo habitual del cliente — sin señales.',
    payload: {
      customer_id: 'CU-0643',
      amount: '864.07',
      currency: 'EUR',
      country: 'PE',
      channel: 'web',
      device_id: 'D-0643',
      timestamp: '2025-12-01T01:45:00+00:00',
      merchant_id: 'M-038',
      issuer_bank: null,
    },
  },
  {
    id: 'challenge',
    label: 'Monto y horario inusual',
    description: 'Bien por encima del promedio habitual, fuera de la ventana horaria (FP-01).',
    payload: {
      customer_id: 'CU-0587',
      amount: '7748.52',
      currency: 'EUR',
      country: 'ES',
      channel: 'web',
      device_id: 'D-0587',
      timestamp: '2025-12-02T01:14:00+00:00',
      merchant_id: 'M-035',
      issuer_bank: null,
    },
  },
  {
    id: 'escalate',
    label: 'Cuenta nueva, monto grande',
    description: 'Cuenta con menos de 30 días y un monto que excede el promedio del segmento (FP-08).',
    payload: {
      customer_id: 'CU-0054',
      amount: '11724.09',
      currency: 'USD',
      country: 'US',
      channel: 'web',
      device_id: 'D-0054',
      timestamp: '2025-12-01T18:36:00+00:00',
      merchant_id: 'M-009',
      issuer_bank: null,
    },
  },
]

export function transactionIdParaEscenario(escenarioId: string): string {
  return `LIVE-${escenarioId}-${Date.now()}`
}
