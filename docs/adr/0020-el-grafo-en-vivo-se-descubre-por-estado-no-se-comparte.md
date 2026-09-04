# ADR-0020: Dashboard descubre ejecuciones en curso por estado, no por estado compartido

- **Estado**: aceptado
- **Fecha**: 2026-09-04

## Contexto

ADR-0019 sirve costo/latencia al dashboard, pero es un número que se
actualiza solo cada 30s — no hay nada que avise cuando un caso termina de
correr y ese número por fin quedó al día. El usuario pidió una forma de
enterarse de eso **aunque la ejecución se haya disparado desde otra
pestaña** — el caso de uso explícito es: alguien ejecuta un escenario en
Transactions y cambia a Dashboard a mitad de la corrida.

`selectedId` (qué caso mirar) hoy vive como estado local de
`Transactions.tsx` — se pierde al desmontar la ruta. La pregunta de diseño
es cómo Dashboard se entera de que hay algo corriendo, sin ese estado.

> **Nota**: la primera versión de esta etapa agregaba, al costado de la
> tabla, la misma animación de grafo en vivo que ya existe en Transactions
> (`GraphPanel` en modo vertical). Se probó, se evaluó contra el resultado
> real y se descartó — no aportaba suficiente frente al costo visual de un
> panel más. La decisión de *cómo descubrir la ejecución en curso* y
> *cuándo refrescar la tabla* (lo que sigue en este documento) no cambió:
> sigue siendo la forma de mantener "Costo y latencia por nodo" al día sin
> esperar el próximo ciclo de 30s, ya sin el grafo como consumidor.

## Decisión

**Dashboard descubre por estado, no por estado compartido.** Sondea
`GET /api/v1/cases?status=ANALYZING&limit=1` (mismo filtro que ya usa la
Cola, `Queue.tsx`, con el mismo intervalo de 8s) y, si encuentra un caso,
se suscribe a su progreso con el mismo `useCaseProgress` que ya usa
Transactions — sin tocar `Transactions.tsx` en absoluto. Cuando el stream
avisa `done`, dispara un `GET /api/v1/metrics/llm?force=true` puntual y
escribe el resultado directo en la caché de React Query
(`queryClient.setQueryData`), para que la tabla de costo se actualice en
el mismo instante, no en el próximo ciclo de 30s.

## Alternativas descartadas

**Compartir `selectedId`/el caso activo entre rutas** (contexto de React
global, o localStorage reactivo). Funcionaría, pero sólo para casos
disparados **en esta misma pestaña del navegador** — si otro visitante
dispara algo, o si Dashboard se abre primero sin haber pasado por
Transactions, no se enteraría. Descubrir por estado (`ANALYZING`) es
además más simple: cero estado nuevo que sincronizar entre componentes, y
muestra cualquier ejecución real del sistema, no sólo "la mía" — más
cerca de lo que un reclutador esperaría de un dashboard genuinamente en
vivo.

**Acortar el TTL general del caché de `/metrics/llm`** en vez de un
`?force=true` puntual. Bajarlo a algo como 5s haría que la tabla "se vea
viva" sin tocar el endpoint, pero pegaría a la API de LangSmith en cada
poll de cada pestaña abierta, todo el tiempo — incluso cuando no terminó
nada. `?force=true` sólo se dispara en el momento exacto que importa (el
stream avisó `done`), sin subir la frecuencia de fondo.

**Mostrar varios casos `ANALYZING` a la vez** si dos visitantes ejecutan
casi al mismo tiempo. `limit=1` sólo muestra uno. Caso raro en una demo;
no vale la complejidad de un panel con varios grafos corriendo a la vez
por ahora.

## Consecuencias

**Se gana** una demo genuinamente en vivo —cualquier ejecución real, de
cualquier origen, se refleja en Dashboard sin acción del usuario— sin
tocar `Transactions.tsx` ni introducir estado global nuevo.

**Se paga**: un sondeo adicional cada 8s (`GET /cases?status=ANALYZING`),
del mismo tamaño y criterio que el que ya hace la Cola — no es una carga
nueva para el proyecto, es el mismo patrón aplicado una vez más.
`?force=true` es una segunda forma de pedir el mismo endpoint
(con caché y sin ella) — documentado en el contrato para que no se lea
como dos endpoints con semántica distinta.
