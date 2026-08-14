import createClient from 'openapi-fetch'

import type { paths } from '@/api/schema'

// Sin `baseUrl`: en producción el dashboard se sirve desde la misma app
// FastAPI (StaticFiles detrás de las rutas del API), así que las rutas
// relativas ya apuntan al lugar correcto. En dev, el proxy de Vite
// (vite.config.ts) redirige `/api` y `/health` al backend real.
export const api = createClient<paths>({ baseUrl: '' })
