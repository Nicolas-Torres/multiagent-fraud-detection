# Enmiendas pendientes — Contrato de Interfaz

**Estado**: 8 enmiendas acumuladas hacia **v0.7**. Vigente: **v0.6**.

> Documento de trabajo: se **vacía** al publicar una versión, no se archiva.
> Nunca hay dos.
>
> Las enmiendas de v0.6 se consolidaron en `contrato_de_interfaz.md` y están
> resumidas en [`CHANGELOG.md`](CHANGELOG.md).

---

## 1. Decididas — listas para redactar

### 1.1 §6 se vacía: sus dos pendientes pasaron a ADR

**Toca**: §6, §1.2, §1.5.

Las dos viñetas que llevaban abiertas desde v0.2 quedaron decididas y
documentadas:

| Pendiente | Resolución |
|---|---|
| Convención de tags | [ADR-0008](adr/0008-el-artefacto-de-hand-off-es-el-digest.md): el CD despliega por **digest**; los tags son etiquetas legibles |
| Migraciones | [ADR-0009](adr/0009-migraciones-como-job-de-pre-deploy.md): Job de pre-deploy, mismo digest, una instancia, **compatible hacia atrás** |

§1.5 pasa de *"tags inmutables: semver + git SHA"* a la tabla de eventos del
ADR-0008, y agrega que **el tag de git es la fuente de verdad de la versión** —
`pyproject.toml` deja de ser autoridad sobre el número.

§1.2 incorpora las condiciones que faltaban: el Job corre con el digest que se va
a desplegar, en una sola instancia, y su falla aborta el rollout.

**Nuevo en §1.2**: *expand / contract*. Toda columna nace nullable; retirar algo
cuesta dos releases; **nunca un `DROP COLUMN` en la misma release que deja de
usarla**. No es una regla sobre dónde corre la migración sino sobre cómo se
escribe, y ya se venía cumpliendo sin nombrarla.

Con esto **§6 queda vacío por primera vez desde v0.2.**

### 1.2 §1 gana un tercer momento de ejecución: el seed

**Toca**: §1.2 (que hoy describe dos modos de arranque).

[ADR-0010](adr/0010-seed-como-job-de-post-deploy.md): el CD ejecuta el seed como
**Job de post-deploy**, con el mismo digest, después de la migración y **sin
`--reset`**.

```
# Modo servir (proceso principal)
uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT}

# Modo migrar (Job de PRE-deploy, aborta el rollout si falla)
alembic upgrade head

# Modo sembrar (Job de POST-deploy, idempotente, NO aborta el rollout)
python scripts/seed.py
```

**Por qué la asimetría**: la migración es obligatoria para que la aplicación
arranque; el seed carga datos y el sistema funciona sin ellos. Un seed fallido
deja un dashboard vacío, no un servicio roto.

> ⚠️ `--reset` ejecuta `TRUNCATE ... CASCADE` y **arrastra los casos, decisiones
> y resoluciones humanas** — la evidencia del entregable 8. Es herramienta de
> desarrollo local y del runbook: **no aparece en ningún pipeline.**

> El seed también **construye el índice vectorial** ([ADR-0012](adr/0012-el-indice-vectorial-es-dato-derivado-y-versionado.md)),
> y sin `GEMINI_API_KEY` lo omite con aviso en vez de abortar: el resultado es un
> estado previsto y medido —*chunks pendientes de indexar*, §1.7—, no una falla.

### 1.3 §1.5 explicita el acceso a GHCR

**Toca**: §1.5.

El paquete queda **privado** y el CD se autentica con un token con
`read:packages`.

**Por qué se escribe**: GHCR es privado por defecto y el `docker pull` falla con
un error de autenticación que se lee como "la imagen no existe". Es el tipo de
detalle que cuesta una tarde el día del despliegue y treinta segundos ahora.

### 1.4 §1.4 gana la variable `ENVIRONMENT`

**Toca**: §1.4 (tabla de variables de entorno).

| Variable | Ejemplo |
|---|---|
| `ENVIRONMENT` | `local` \| `staging` \| `production` |

**Por qué**: es lo que habilita el guard de `--reset`
([ADR-0010](adr/0010-seed-como-job-de-post-deploy.md)). El script solo permite la
operación destructiva con `ENVIRONMENT=local`, así que la variable **ausente
rechaza** — el default seguro.

Consecuencia para el CD: hay que inyectarla en todos los ambientes, incluidos
los Jobs de migración y de seed. Si falta, la aplicación funciona igual; lo único
que cambia es que `--reset` queda bloqueado, que es el comportamiento deseado.

### 1.5 §2.5 — el invariante de `citations_internal` se redacta como contención

**Toca**: §2.5, §7.3 (guarda 1).

La formulación vigente pide, cuando `decision != ESCALATE_TO_HUMAN`, que
`citations_internal` sea **no vacío**. Está mal por dos lados opuestos.

**Es demasiado débil.** Una lista con las citas equivocadas la satisface: el motor
dispara FP-03, el índice devuelve FP-05 y FP-02, el caso se decide `BLOCK`
—correctamente— y **cita normas que no aplicó**. No hay excepción, el invariante
se cumple, y el auditor recibe una explicación coherente y falsa. Ninguna huella
lo detecta: los dos artefactos están intactos, lo que falló fue el emparejamiento.

No es hipotético. En el smoke de la etapa, un `BLOCK` disparado por FP-03 recuperó
además FP-09, FP-04, FP-11 y FP-01, **ninguna de las cuales disparó**. Con la
formulación débil, ese conjunto habría alcanzado para respaldar el veredicto.

**Y es insatisfacible para `APPROVE`.** El catálogo rechaza al cargar cualquier
vinculación con `action: APPROVE` —*"`action` no puede ser APPROVE"*—: ninguna
norma prescribe aprobar. Entonces ninguna cita puede respaldar una aprobación, y
como el 90% del tráfico no dispara ninguna política, la redacción vigente mandaría
a la cola humana a casi todo el volumen.

Con [ADR-0011](adr/0011-citacion-por-identidad-descubrimiento-por-similitud.md)
la citación se resuelve por identidad, así que el invariante puede afirmar lo
correcto sin exceptuar ningún veredicto:

> Cuando `decision != ESCALATE_TO_HUMAN`: `citations_internal` contiene una cita
> por **cada** `policy_id` de `matched_policies`, y `base_confidence` no es
> `null`.

**La obligación nace de la evidencia, no del veredicto.** Si alguna política
disparó, tiene que estar citada; si no disparó ninguna, no hay nada que exigir y
la condición se cumple vacíamente. Por eso `APPROVE` no necesita una exención: la
recibe de la propia forma del enunciado. Y la exigencia de `base_confidence` no se
toca — una aprobación sin score determinístico sí sería un veredicto sin
fundamento.

**Contiene, no iguala.** La pierna de descubrimiento agrega políticas relacionadas
que no dispararon; eso es aporte al Arbiter, no violación.

La guarda 1 de §7.3 se endurece con el mismo texto. Sigue **levantando, no
reparando**: el Arbiter degrada a `ESCALATE_TO_HUMAN` antes de que pueda
dispararse —la ausencia de respaldo es la razón de llamar a un humano, no un error
del sistema—, así que llegar a W2 en violación es un defecto del Arbiter.

**Cambio de texto, no de esquema.** Lo que cambia es lo que el dashboard puede
asumir: en todo caso `DECIDED`, cada política que disparó tiene su cita.

> **Queda fuera, deliberadamente**: la cláusula recíproca —*aprobar exige que no
> haya disparado nada*—. Convertiría en error el override pro-cliente que un
> Arbiter con LLM podría querer hacer con justificación. Se decide en la rama del
> Arbiter, con el caso real a la vista en vez de prohibido de antemano.

### 1.6 §2.5 y §7.1 — `decisions.retrieval_index_version`

**Toca**: §2.5 (tabla de `Decision`), §7.1 (notas de `decisions`).

| Campo | Tipo | Notas |
|---|---|---|
| **`retrieval_index_version`** | `str \| null` | 🆕 con qué generación del índice se recuperó: modelo, dimensión, plantilla y generación (`gemini-embedding-2:1536:doc:1`) |

Junto a `scoring_version` y `policy_catalog_version` cierra la auditoría en tres
ejes ([ADR-0012](adr/0012-el-indice-vectorial-es-dato-derivado-y-versionado.md)):

| Eje | Sello |
|---|---|
| Qué texto se citó | `InternalCitation.version` |
| Qué traducción se evaluó | `policy_catalog_version` |
| Con qué índice se recuperó | **`retrieval_index_version`** |

**El `null` significa algo y el dashboard puede leerlo.** No es dato faltante: es
*"este veredicto no usó el índice"*. Ocurre en dos casos previstos —una
transacción sin señales utilizables no tiene nada que preguntar, y un caso con el
proveedor de embeddings caído recupera nada—. Sellar la versión igual afirmaría
que un índice participó en una decisión donde no participó.

**Cadena descriptiva, no id opaco**: el motivo de sellarla es que alguien la lea.
Por lo mismo el modelo **no** es configurable por `env`: cambiarlo sin subir la
versión sellada haría mentir a los tres sellos a la vez. Por `env` viaja sólo
`GEMINI_API_KEY`, ya en §1.4.

Nullable también por *expand / contract* (§1.2): las decisiones ya persistidas no
tuvieron índice.

### 1.7 §3.3 — tercera métrica operativa del entregable 6

**Toca**: §3.3.

Hoy §3.3 declara dos —*pendiente de vinculación* y *vinculación obsoleta*—. Se
suma **chunks pendientes de indexar**.

Un documento publicado y no indexado es **citable por identidad e invisible por
similitud**: si dispara, la pierna de autorización lo cita igual —esa pierna no
consulta el índice—; si no dispara, no hay forma de que aparezca. Es un estado
legítimo —publicar la norma hoy y componer la vinculación después es uso previsto,
y §3.3 ya lo declara así— y **silencioso**: nada falla.

Las tres métricas son la misma clase de cosa: desincronizaciones entre artefactos
con dueños distintos. La norma sin vinculación no se evalúa; la norma sin chunk
no se descubre; la huella rota deja de evaluarse sin dejar de citarse.

### 1.8 §7.1 — de ocho tablas a doce

**Toca**: §7.1.

Dos cosas: una de arrastre y una nueva.

**De arrastre.** El encabezado dice *"Las siete tablas"* y la sección lista
**ocho**. Cuando entró `merchant_blacklist`, su fila quedó separada por una línea
en blanco: renderiza como una tabla huérfana de una fila, y el conteo del título
nunca se actualizó. Se repara al reescribir la sección.

**Nueva.** Las cuatro tablas de la etapa, en orden de FK:

| Tabla | PK | Notas |
|---|---|---|
| **`fraud_policies`** | `(policy_id, version)` compuesta | 🆕 documento normativo; append-only por versión. **Sin `active`**: el estado se deriva |
| **`binding_sets`** | `version` (`2025.1-b1`) | 🆕 encabezado del set; a lo sumo uno activo, por **índice parcial único** |
| **`policy_bindings`** | `(binding_set_version, policy_id)` | 🆕 FK compuesta a `fraud_policies(policy_id, version)`; `condition` JSONB nullable |
| **`policy_chunks`** | `(index_version, chunk_id)` | 🆕 `embedding vector(1536)`; **ningún índice extra**: la PK ya sirve el filtro por generación |

Total: **doce**. Sigue faltando `web_search_allowlist` (§4), que espera a su
consumidor.

> **Por qué `fraud_policies` no lleva `active`.** El patrón de
> `merchant_blacklist` invita a copiarla, pero ahí la bandera **es** el dato: la
> pertenencia a la lista negra es lo que se administra, y la baja lógica es su
> audit trail. En el catálogo, en cambio, los cuatro estados son **derivados**
> ([ADR-0007](adr/0007-la-forma-ejecutable-de-una-politica-es-una-vinculacion.md):
> derivar, nunca escribir). Una columna `active` en el documento sería una
> segunda fuente de verdad sobre *¿esta política aplica?*, compitiendo con
> `PolicyState`. El retiro ya es expresable —`policy_bindings.active = false` →
> `EXCLUDED`, que el loader ya lee— y, como la tabla es append-only por
> `(policy_id, version)`, no publicar vinculación para la versión nueva también
> es un retiro.

> **Por qué la FK compuesta importa.** `policy_bindings (policy_id,
> source_version)` → `fraud_policies (policy_id, version)` convierte en
> **estructura** la validación 5 del catálogo, que hoy es código: una vinculación
> no puede apuntar a un documento inexistente porque la base no la deja entrar.

---

## 2. Abiertas — falta decidir

*(ninguna)*

> **ADR-0008 a ADR-0010** siguen en estado **propuesto**. Son de §1, que valida
> el compañero: se publican en v0.7 cuando él acuse recibo, o por decisión por
> defecto si no hay objeción en la fecha acordada.
>
> **ADR-0011 a ADR-0013** están **aceptados**: son de §2, §3 y §7, que valido yo.

---

## 3. Hallazgos que **no** tocan el contrato

Van al repaso de etapa. Se anotan acá para no perderlos.

### 3.a — RAG de políticas internas → acta 06 *(cerrado al abrir la etapa)*

- **La forma compartida era menos de la supuesta.** La nota original daba por
  hecho que las tres tablas de gobernanza llevan `active`, `added_by`, `added_at`
  y `reason`, y que modelarlas juntas salía más barato. No comparten eso:
  `bound_by` / `bound_at` cargan el sentido de ADR-0007 —quién tradujo la norma y
  cuándo— y no se uniforman con la fecha de alta de un comercio en una lista
  negra. **Lo que sí tiene dos consumidores reales, y por eso se extrae, es el
  repositorio con caché TTL** de `merchant_blacklist`.

- **Alcance decidido**: cuatro tablas (§1.8). `web_search_allowlist` sigue sin
  consumidor hasta el Threat Intel Agent, por el criterio que el proyecto ya usó
  dos veces: una tabla sin quien la lea es deuda, no previsión.

- **El guard de `--reset` por variable de entorno ya existe** (`ef59b38`):
  `settings.permite_operaciones_destructivas` y el rechazo explícito en
  `seed.py`. La variable entró como enmienda §1.4. Hallazgo cerrado.

### 3.b — Hallazgos de la etapa → acta 06

- **El árbitro determinístico se adelantó.** El plan lo ponía al final de la rama
  y marcado como *"lo primero que se corta"*. Se adelantó porque sin él ningún
  caso llega a `DECIDED`, las tres guardas de W2 no se ejercitan y el paso de
  ablación no tiene de dónde sacar *"cuántos casos salen de
  `ESCALATE_TO_HUMAN`"*. Es el brazo de control que ADR-0006 prometió.

- **La ablación va a estar sesgada a favor del descubrimiento, y hay que
  publicarlo con el número.** La query se arma con las `description` de los
  predicados, y con un chunk por documento el índice contiene casi ese mismo
  texto: en el smoke, FP-03 salió primera de la búsqueda hecha con la señal que
  ella misma produce. El recall@k va a ser alto por construcción, no por mérito.
  Es la contracara del límite ya declarado —*el corpus de once líneas
  sobredimensiona la pierna de identidad*—: también sobredimensiona la otra.

- **Una prueba que no puede fallar es peor que no tenerla.** La primera versión
  de `smoke_retrieval.py` comparaba conjuntos de `chunk_id` entre generaciones
  para verificar el filtro por `index_version`. No prueba nada: una fila se
  identifica por `(index_version, chunk_id)` y el `chunk_id` es idéntico entre
  generaciones **por diseño**. Una de las dos comprobaciones dio falso positivo
  —se notó— y la otra habría dado verde para siempre. Lo que discrimina es el
  conteo y la distancia.
