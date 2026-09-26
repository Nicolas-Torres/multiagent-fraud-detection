import createClient from 'openapi-fetch'

import type { paths } from '@/api/schema'

// Sin `baseUrl`: en producción el dashboard se sirve desde la misma app
// FastAPI (StaticFiles detrás de las rutas del API), así que las rutas
// relativas ya apuntan al lugar correcto. En dev, el proxy de Vite
// (vite.config.ts) redirige `/api` y `/health` al backend real.
export const api = createClient<paths>({ baseUrl: '' })

/**
 * El motivo que explica la API en un error (`{"detail": "..."}`), si es texto.
 * Los errores de validación (422) traen una lista en `detail`: ahí no hay un
 * mensaje para el visitante y se devuelve `null`.
 */
export function motivoDelError(error: unknown): string | null {
  if (typeof error === 'object' && error !== null && 'detail' in error) {
    const detalle = (error as { detail: unknown }).detail
    if (typeof detalle === 'string') return detalle
  }
  return null
}
