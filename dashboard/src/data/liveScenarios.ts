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
      // No CU-0643/T-2579 (el de la vitrina precalculada): ese cliente ya
      // tiene una transacción real sembrada a las 01:45 en PE, y el país
      // habitual del cliente es ES — cualquier corrida en vivo con un país
      // distinto de PE dispara FP-05 (geolocalización imposible) contra esa
      // fila ya existente, y con PE arriesga FP-02 al sufijar el
      // dispositivo (abajo). CU-0426/T-1047 no tiene ese problema: país y
      // dispositivo ya coinciden con su perfil habitual desde el dataset
      // real, sin parches.
      customer_id: 'CU-0426',
      amount: '3248.53',
      currency: 'EUR',
      country: 'ES',
      channel: 'web',
      device_id: 'D-0426',
      timestamp: '2025-12-01T01:59:00+00:00',
      merchant_id: 'M-022',
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

/**
 * Arma la transacción completa para una corrida en vivo, con
 * `transaction_id`, `device_id` y `merchant_id` sufijados con el mismo
 * token único.
 *
 * El timestamp queda fijo (arriba), pero cada clic sí escribe una
 * transacción real y permanente (W0 siempre persiste). Sin este sufijo,
 * varias corridas del mismo escenario —de visitantes distintos, en
 * momentos distintos— acumulan el mismo dispositivo y el mismo comercio en
 * la misma ventana fija, y el motor ve eso correctamente como velocity real
 * (FP-03) o suma diaria real (FP-11): el escenario "Monto y horario
 * inusual" empezaba a derivar hacia BLOCK con el uso, no por un bug sino
 * por evidencia que el propio uso de la demo iba generando.
 *
 * Seguro para los tres escenarios — verificado contra los perfiles reales:
 * ninguno depende de que el dispositivo o el comercio sean "habituales"
 * para producir su veredicto (a diferencia del país, que si importa para
 * FP-02 — por eso el escenario "approve" usa el país real del cliente).
 */
export function transaccionParaCorridaEnVivo(escenario: LiveScenario): TransactionIn {
  const token = Date.now()
  return {
    ...escenario.payload,
    transaction_id: `LIVE-${escenario.id}-${token}`,
    device_id: `${escenario.payload.device_id}-${token}`,
    merchant_id: `${escenario.payload.merchant_id}-${token}`,
  }
}
