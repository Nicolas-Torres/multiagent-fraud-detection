# Enmiendas pendientes — Contrato de Interfaz

**Estado**: 5 enmiendas acumuladas hacia **v0.6**. Vigente: **v0.5**.

> Documento de trabajo: se **vacía** al publicar una versión, no se archiva.
> Nunca hay dos.
>
> Las enmiendas de v0.5 se consolidaron en `contrato_de_interfaz.md` y están
> resumidas en [`CHANGELOG.md`](CHANGELOG.md).

---

## 1. Decididas — listas para redactar

### 1.1 `Decision` gana `matched_policies`

**Toca**: §2.5 (schema `Decision`), §7.1 (tabla `decisions`).

`list[str] | null` en la frontera; `varchar[]` en la tabla. Lo produce el agente
dueño de cada política y lo consolida Evidence Aggregation.

**Por qué**: el ground truth habla en políticas (`expected_policies`); la tabla
`signals` habla en observaciones atómicas (`NEW_DEVICE`, `OUTSIDE_USUAL_HOURS`).
Sin este campo el harness no tiene contra qué comparar: una política es la
conjunción de dos o tres señales, y la correspondencia no es reconstruible desde
las señales sueltas.

Va como `ARRAY` y no como tabla por la regla de §7.2: escalares homogéneos, se
leen siempre completos, no existen sin su dueño. Mismo caso que `agent_route`.

### 1.2 `Decision` gana `policy_catalog_version`

**Toca**: §2.5, §7.1.

Valor inicial: `2025.1-b1`.

**Por qué**: con las políticas como dato mutable
([ADR-0007](adr/0007-la-forma-ejecutable-de-una-politica-es-una-vinculacion.md)),
una decisión de enero evaluada contra el catálogo de marzo deja de ser auditable.
`scoring_version` sella la fórmula de scoring; esto sella la norma aplicada.

Son dos campos y no uno porque cambian por motivos y a ritmos distintos: la
fórmula la toca un ingeniero, el catálogo lo toca el banco.

### 1.3 §4 gana dos tablas de gobernanza, no una

**Toca**: §4 (que hoy habla solo de `web_search_allowlist`).

| Tabla | Dueño del dato | Contenido |
|---|---|---|
| `fraud_policies` | el banco | documento normativo: `policy_id`, `version`, `text` |
| `policy_bindings` | nosotros | traducción: `condition`, `action`, `excluded_reason`, `source_fingerprint`, `bound_by`, `bound_at` |

Ciclos de vida **independientes**: el banco publica o edita un documento sin tocar
la vinculación, y la vinculación se rehace sin tocar el documento. Ambas llevan
`active` y audit trail, como `merchant_blacklist`.

**Entran con su consumidor** —el RAG, que lee los documentos para indexarlos—, por
el mismo criterio con el que se difirió `web_search_allowlist`.

**Por qué**: una política de fraude es dato de gobernanza —mutable, administrado
por un humano, con audit trail— por la misma regla que §4 ya enuncia.

### 1.4 §6 pierde la viñeta de zona horaria

**Toca**: §6.

Ya está cerrada en §2.7 desde v0.5 (*"el supuesto `America/Lima` está muerto"*), y
`CustomerBehavior.timezone` existe en modelo, schema y dataset. §6 quedó
desactualizado.

**Nota de proceso**: al cerrar una etapa hay que revisar §6, no solo agregar a §5.

### 1.5 El dashboard gana una tercera vista: políticas

**Toca**: §3 (hoy define dos vistas: cola y detalle), §2.3 (endpoints).

**Lista**: las políticas con su estado —activa, excluida, pendiente de
vinculación, vinculación obsoleta—.

**Alta**: un formulario en dos secciones. La norma (`policy_id`, `version`, texto)
es obligatoria; la vinculación (acción + predicados compuestos desde un
desplegable) es opcional. Sin vinculación la política queda citable por el RAG y
no evaluable por el motor — es un uso previsto, no un error.

Endpoints nuevos: `GET /api/v1/policies`, `POST /api/v1/policies`,
`GET /api/v1/predicates` (la biblioteca, para alimentar el compositor).

**Por qué**: cierra el ciclo de gobernanza que ADR-0007 abrió. Sin una vista,
agregar una política sigue siendo editar un JSON a mano, que es exactamente lo que
el ADR existe para evitar. Y hace visible el modelo en la demo del entregable 8:
una tabla donde FP-10 dice "excluida" comunica en diez segundos lo que el ADR
explica en tres páginas.

**Consecuencia sobre la rama de agentes determinísticos**: la biblioteca de
predicados debe exponer sus parámetros como dato (nombre, tipo, rango, etiqueta),
no solo como firma de Python.

---

## 2. Abiertas — falta decidir

### 2.1 Los dos pendientes de §6 no son decisiones, son confirmaciones

**Migraciones** y **convención de tags** llevan abiertos desde v0.2 —cuatro
versiones—. La postura está redactada y argumentada; falta el acuse de recibo del
compañero, porque ambos son de §1, que él valida.

Propuesta: convertirlos en **ADR-0008**, con decisión por defecto si no hay
objeción antes de una fecha. Es bloqueo real del entregable 5: no se puede
escribir el paso de publicación de CI sin saber qué tags emite.

Tres precisiones que agregar antes de mandarla:

- **Compatibilidad hacia atrás de las migraciones.** Durante el rollout conviven
  la imagen vieja y la nueva, así que la migración tiene que funcionar con las dos
  (*expand/contract*: columna nullable, backfill, `NOT NULL` después). Ya se viene
  cumpliendo sin nombrarlo.
- **El CD despliega por digest**, no por tag. Un tag se puede mover; un digest no.
- **GHCR es privado por defecto.** El compañero necesita credenciales con
  `read:packages`, o el paquete se hace público.

---

## 3. Hallazgos que **no** tocan el contrato

Van al repaso de etapa. Se anotan acá para no perderlos. Agrupados por la etapa
que los produjo: al cerrar, cada bloque va a su acta.

### 3.a — Agentes determinísticos → acta 05

- **"Agentes de lógica pura" es un nombre inexacto** y se abandona. Dos de los
  tres nodos hacen I/O: Behavioral consulta historial, Context consulta la lista
  negra. Lo puro es la capa de reglas que vive debajo. Vocabulario fijado:
  `domain/` son **reglas puras**; los nodos son **agentes determinísticos**;
  "agente" a secas es cualquier nodo del grafo.

- **El término "agente" se sostiene en su acepción clásica.** Los tres nodos son
  agentes reflexivos en el sentido de la IA de manual —Behavioral es *model-based*:
  su modelo interno del mundo es el perfil del cliente—. El argumento va explícito
  en el informe: seis de nueve agentes con LLM es un número fuerte, pero no
  argumentado alguien cuenta LLMs y resta.

- **El primer diseño de políticas-como-dato metía campos nuestros dentro del
  documento del banco.** Se corrigió al notar que ese artefacto tiene dueño
  externo. La garantía de no divergencia se conserva por **huella del texto**, que
  no requiere tocar el original. Lección transversal: *antes de agregar un campo,
  preguntar de quién es el archivo*.

- **El reparto Context / Behavioral no se eligió: se derivó.** Sale de los insumos
  que declara cada predicado, y coincide exactamente con la rama `if perfil is
  None` de `build_ground_truth.py`. Resultado 1 contra 9. Context es el piso de
  evidencia, el único que sigue produciendo señales cuando el cliente no existe.

- **"Tool" no implica LLM.** El malentendido frecuente es que consultar la base
  desde un agente requiere un modelo que decida la consulta. En Behavioral esa
  decisión no existe: el historial se necesita siempre. Un LLM ahí agregaría dos
  llamadas por caso, rompería la reproducibilidad del harness y —lo más grave—
  podría pasar `as_of=now()`, un bug que **no se ve en producción** y solo aparece
  en evaluación, inflando el recall. *Text-to-SQL* sigue siendo buen candidato para
  la exploración ad hoc del analista (entregable 10), que es otro problema.

- **FP-03 tiene dos ejes en conflicto.** `transaction_history.py` documenta que
  `history_for_device` deliberadamente **no** filtra por cliente; el etiquetador
  evalúa la ventana sobre `por_cliente[customer_id]` filtrando por dispositivo.
  Medido: 1 337 dispositivos, 27 compartidos entre clientes, 77 transacciones
  involucradas, y **cero divergencia** entre criterios (59 positivos idénticos).
  Contradicción latente, no activa — pero produce falsos positivos el día que el
  dataset cambie.

- **El etiquetador excluye FP-03 y FP-05 de las transacciones sin perfil**, aunque
  ninguna dependa del perfil: la rama `if perfil is None` hace `continue` tras
  evaluar FP-07. Verificado que hoy ninguna dispararía (0 y 0), pero el motor tiene
  que replicar la exclusión o el harness le cobra falsos positivos que no existen.

- **En esta etapa no se puede medir la decisión, solo las políticas.**
  `_verificar_invariantes` exige `citations_internal` no vacío para todo veredicto
  autónomo; sin RAG la lista está vacía y todos los casos terminan en
  `ESCALATE_TO_HUMAN`. El F1 de `expected_decision` no es medible hasta la etapa
  siguiente. Lo que sí se mide, sobre las 7 000 y en offline, es `expected_policies`.

- **Los promedios por segmento son un agregado poblacional.** Calculados en runtime
  se mueven con la población y hacen irreproducible el harness sin que nada falle;
  además el perfil es mutable, así que consultarlos viola el espíritu del
  invariante *as-of*. Se congelan como parámetro versionado: `retail 634.35` ·
  `premium 1847.59` · `business 4778.64` USD.

- **Dos métricas operativas nuevas para el entregable 6**: *políticas pendientes* y
  *vinculaciones obsoletas*. Salen gratis del modelo de huellas y son el tipo de
  indicador que un área de cumplimiento quiere ver.

- **Deuda registrada: *shadow mode*.** Una vinculación nueva no tiene ground truth;
  el validador atrapa errores de forma, no de semántica. Activar una política sin
  correrla antes contra tráfico histórico convierte la agilidad en una forma rápida
  de bloquear clientes legítimos. Va al entregable 10.

- **Convenciones de nombre de rama divergentes**: `feature/*` en kebab-case frente
  a `feat/AGENT-0001`. Sin urgencia, pero conviene cerrarlo al revisar la rama de
  infraestructura.
