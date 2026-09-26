# ADR-0026: cada llamada a un LLM usa el modelo más chico que alcanza, y lo declara

- **Estado**: aceptado
- **Fecha**: 2026-09-26

## Contexto

El incidente 0010 midió el gasto real en LangSmith (7 días):

| Llamada | Modelo | n | Entrada media | Salida media |
|---|---|---|---|---|
| `fetch-intel` | Sonnet 4.6 | 105 | 15 304 | 1 205, cortada 100 de 105 veces |
| Narrador (debate ×2 y explicación) | Sonnet 5 | 156 | 582 | 232 |
| Árbitro | Sonnet 5 | 52 | 1 804 | 266 |

Tres hechos pesan en la decisión:

1. **`fetch-intel` es casi todo el gasto**, unos USD 1.1 por día aunque la demo
   no tenga visitas. Lo que se paga es:
   - la entrada: los resultados que la herramienta de búsqueda le devuelve al
     modelo para que redacte;
   - la salida: un informe en prosa que `searcher._extraer` descarta entero,
     porque la URL, el título y la fecha salen de los bloques de resultado
     (ADR-0014).

   En la demo, además, ese corpus no influye: FP-10 mira las 24 h previas al
   timestamp de la transacción, y los escenarios tienen fechas fijas de
   diciembre de 2025. Ninguna de las 54 decisiones en producción lo usó.
2. **La explicación al cliente es una redacción acotada**: temas ya traducidos
   (`SAFE_THEMES`), sin identificadores, 2 a 4 oraciones. No razona sobre la
   evidencia; eso lo hacen el debate y el árbitro.
3. **El sello del debate no describía lo que corría.** El debate llamaba al
   narrador compartido, que usaba el modelo y el tope de `explain/customer.py`.
   El `MODEL` y el `MAX_TOKENS = 300` de `debate/pro_*.py` no se aplicaban nunca:
   coincidían por casualidad.

## Decisión

**Cada llamada usa el modelo más chico que alcanza para su tarea, y el módulo que
sella la versión es el que le dice al adaptador qué modelo usar.**

- **`fetch-intel`**:
  - modelo: `claude-haiku-4-5-20251001` (ID con fecha, fijo);
  - un prompt de sistema que pide una sola búsqueda y ninguna prosa;
  - `max_tokens = 100`: la búsqueda ocurre antes del texto, así que el tope sólo
    corta la prosa;
  - `GENERATION = 2`;
  - cadencia semanal (`0 6 * * 1`) en vez de diaria.
- **Explicación al cliente**: `claude-haiku-4-5-20251001`. Sube
  `explanation_prompt_version`.
- **Debate y árbitro**: siguen en `claude-sonnet-5`. Su salida alimenta el
  veredicto.
- **`Narrator.narrate(system, user, *, model, max_tokens)`**: el adaptador ya no
  tiene modelo ni tope propios. Cada nodo le pasa los de su módulo, el mismo
  módulo que arma el `PROMPT_VERSION`. El `MAX_TOKENS` del debate pasa a 400, el
  valor que de hecho corría: sus salidas llegan a 378 tokens y un tope de 300
  las cortaría.

Verificado antes de implementar, con una llamada real: Haiku 4.5 acepta
`web_search_20250305`, hace una sola búsqueda y devuelve 10 resultados. Con
`max_tokens = 100`, la salida baja a ~170 tokens y los resultados quedan
intactos.

## Alternativas descartadas

**Mantener la cadencia diaria.** En la demo no cambia ninguna decisión, y cuesta
7 veces más.

**Apagar `fetch-intel`.** Es el ahorro máximo, pero se pierde el pipeline de
inteligencia externa gobernada (ADR-0014), que es parte de lo que el proyecto
demuestra. Semanal lo mantiene vivo y verificable.

**Debate en Haiku.** Su argumento es la entrada del árbitro: uno más pobre puede
mover el veredicto. El ahorro no lo justifica, porque sus tokens ya son pocos.

**Salida estructurada (JSON) en el debate y la explicación.** El texto es el
producto: se persiste y se muestra completo. Un JSON no lo acortaría. El árbitro
ya usa salida estructurada.

**Una API de búsqueda sin LLM** (Brave, Google). Eliminaría el costo de tokens,
pero suma un proveedor, una clave y un contrato nuevos para un corpus que hoy no
influye en la demo.

## Consecuencias

**Se gana**:

- `fetch-intel` pasa de ~USD 0.074 por búsqueda a ~USD 0.02, y de 30
  ejecuciones al mes a 4: de ~USD 33 a ~USD 1.2 al mes.
- La explicación cuesta ~3 veces menos.
- El sello de cada llamada describe lo que de verdad corrió. Un test lo verifica.

**Se paga**:

- `SNAPSHOT_VERSION` pasa a `claude-haiku-4-5-20251001:issuer-alert:v2`. El
  lookup filtra por versión exacta: el corpus v1 deja de verse hasta que corra
  el fetch nuevo. Se ejecuta una vez a mano después del deploy.
- Con cadencia semanal, una alerta publicada un martes no se ve hasta el lunes
  siguiente. Para la demo no importa (fechas fijas). Un despliegue real tendría
  que volver a una cadencia acorde a la ventana de FP-10.
- La explicación de Haiku puede redactar distinto que la de Sonnet. Las reglas
  que la protegen (sin umbrales, códigos ni identificadores) son las mismas y
  siguen en el prompt.

## Nota (2026-09-26): la explicación al cliente vuelve a Sonnet 5

La parte de la explicación se revirtió el mismo día. El resto de la decisión
sigue vigente: fetch-intel en Haiku, sin prosa y semanal, y el modelo declarado
en cada llamada.

En producción, Haiku 4.5 cumplió las reglas de divulgación, pero omitía los
motivos seguros. Para el escenario "Monto y horario inusual":

- **Sonnet 5:** "…presenta un importe distinto al que sueles manejar, se realizó
  desde un dispositivo que no habíamos visto antes en tu cuenta y en un horario
  poco frecuente…".
- **Haiku 4.5:** "Hemos detectado esta operación y necesitamos verificar tu
  identidad…", sin ningún motivo.

Con el mismo prompt, Haiku nombró 0 de 3 temas en dos llamadas. Con un prompt
que exigía nombrarlos todos, los nombró en una de dos llamadas.

La explicación es lo que más se ve de la demo, y el ahorro era de ~USD 0.003
por decisión. El juicio de "el modelo más chico que alcanza" dio que, para esta
tarea, Haiku no alcanza. La explicación queda en `claude-sonnet-5`, con el
mismo `explanation_prompt_version` que antes de este ADR. La decisión sellada
con `claude-haiku-4-5-20251001:customer:1` durante la prueba sigue siendo
verdadera: dice qué modelo la redactó.
