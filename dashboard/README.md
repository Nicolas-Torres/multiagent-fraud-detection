# Dashboard del analista

Frontend del [Sistema Multi-Agente de Detección de Fraude](../README.md) —
React + TypeScript + Vite + Tailwind v4 + shadcn/ui, consumiendo la frontera
HTTP que describe [`docs/contrato_de_interfaz.md`](../docs/contrato_de_interfaz.md)
(§2 y §3).

Qué muestra cada vista, con el porqué: [`docs/briefing_dashboard.md`](../docs/briefing_dashboard.md).

## Vistas

| Ruta | Archivo | Qué es |
|---|---|---|
| `/` | `Dashboard.tsx` | Costo y latencia por nodo, en vivo (LangSmith, ADR-0019/0020) |
| `/transactions` | `Transactions.tsx` | Vitrina curada + escenarios "ejecutar en vivo", grafo y debate en tiempo real por SSE (ADR-0018) |
| `/queue` | `Queue.tsx` | Cola HITL — casos en `PENDING_HUMAN` |
| `/cases/:caseId` | `CaseDetail.tsx` | Detalle completo de un caso: señales, citas, debate, resolución |
| `/policies` | `Policies.tsx` | Catálogo de políticas y su estado |
| `/architecture` | `Architecture.tsx` | Cómo se construyó — C4, topología del grafo, ADRs curados |

## Puesta en marcha

```bash
npm install
npm run dev          # servidor de desarrollo, proxy a la API local
```

Requiere el backend corriendo aparte (ver el
[README raíz](../README.md#puesta-en-marcha)) — este proyecto no trae su
propia base de datos ni sus propios proveedores.

## Tipos generados, no escritos a mano

```bash
npm run generate:api    # openapi-typescript contra la app real -> src/api/schema.d.ts
npm run generate:graph  # topología del grafo compilado -> src/data/graph_topology.json
```

Ambos se generan **contra el sistema real**, nunca se editan directamente —
mismo principio que los diagramas del README raíz: lo que deriva no se
dibuja ni se tipa a mano.

## Verificación

```bash
npm run build   # tsc -b && vite build
npm run lint    # oxlint
```

## Empaquetado

No se despliega por separado: el `Dockerfile` en la raíz del repo compila
este proyecto en una etapa y lo sirve como estáticos desde la misma imagen
de FastAPI (`StaticFiles`, con catch-all a la SPA) — una sola imagen, un
solo digest, mismo artefacto en Azure y en GCP.
