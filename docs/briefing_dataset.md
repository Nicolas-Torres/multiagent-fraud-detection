# Briefing — Etapa "Dataset, campos nuevos, índices y seed"
> ⚠️ **Documento consumido.** Su función era inicializar la etapa de dataset y
> seed; eso ya ocurrió. Dos partes quedaron equivocadas o superadas:
>
> - **§7, §8 y §10** describen un alcance, una lista de peticiones al equipo de
>   banca y unas preguntas abiertas que ya se resolvieron. El estado actual está
>   en [`enmiendas_pendientes.md`](enmiendas_pendientes.md).
> - **La numeración de políticas está corrida** a partir de la octava: el
>   análisis leyó los comentarios del generador en vez del catálogo. El catálogo
>   real es `FP-01`…`FP-11` **sin huecos**. No falta `FP-08` ni existe `FP-12`.
>   Donde el documento diga FP-09, FP-10, FP-11 y FP-12, léase FP-08, FP-09,
>   FP-10 y FP-11.
>
> El resto —los hechos medidos sobre el dataset original (§3–§5) y el argumento
> de las decisiones (§6)— sigue siendo válido y es la materia prima del acta de
> etapa. Se borra al cerrarla.

---

## 1. Punto de partida

Construido y en `main`: infraestructura local (Postgres 18 + pgvector, Alembic),
seis tablas con sus schemas de frontera, el esqueleto del grafo —`GraphState`,
topología de siete supersteps, degradación ante caída de un agente— y la
persistencia de la decisión con sus columnas de scoring. Los nueve agentes son
stubs.

**Nada de lo construido se invalida con el dataset.** La topología no se toca:
el agente de secuencias que hará falta (§7) lee la transacción y consulta la BD,
no lee lo que otro nodo escribe → cae en la ola 0 como los otros tres.

### Lo que cambió debajo

Existe una **base compartida en AWS RDS** (PostgreSQL 18.3, base `fraud`) donde
ambos desarrollamos. Mi compañero construye el dashboard contra ella y hoy tiene
las seis tablas **vacías**: un dashboard sin filas no se puede diseñar, ni
siquiera equivocándose.

Eso reordena la prioridad de esta etapa. No es la siguiente por orden lógico —lo
sería igual—, es **la que lo desbloquea a él**. El resto del sistema puede
esperar; su trabajo no.

Local subió de 17 a 18 para alinear con RDS: mientras difirieran, "pasa en local"
dejaba de ser evidencia de "pasa en la nube". La forma de `DATABASE_URL` cambió
con ello (`?sslmode=require`, password percent-encoded) → `enmiendas_pendientes.md`
§1.5–1.7.

---

## 2. El insumo

Tres archivos del equipo de banca:

| Archivo | Contenido |
|---|---|
| `transactions.csv` | 7 000 transacciones |
| `customer_behaviors.csv` | 1 000 perfiles de comportamiento |
| `fraud_policies.json` | 11 políticas, `FP-01` … `FP-11`, versión `2025.1` |

Generados por un script con `numpy.random.seed(42)`, reproducible.

### Ubicación propuesta en el repo

```
data/
├── transactions.csv                  # ~493 KB
├── customer_behaviors.csv            # ~79 KB   ← plural, igual que la tabla
└── policies/
    └── fraud_policies_2025.1.json
scripts/
└── generate_data.py               # el generador, como procedencia
```

- `data/` y no `docs/` ni `src/`: es insumo del dominio.
- **Plural en `customer_behaviors.csv`** para que el nombre coincida con la
  tabla que carga.
- **La versión en el nombre del JSON de políticas.** A diferencia del contrato
  —que tiene una sola verdad vigente— las políticas versionadas conviven: un
  caso decidido en enero cita `FP-01 v2025.1`, y esa cita debe seguir siendo
  legible cuando exista `2025.2`. Por eso `InternalCitation` tiene `version`.
- **Se commitean los CSV**, no solo el generador: el `seed(42)` es determinista
  *dentro de una versión de numpy*. Los CSV son el artefacto de registro.
- **`pandas` y `numpy` van a dependencias de dev**, no a `dependencies`. Solo
  las usa el generador; en `dependencies` cargarían ~150 MB de dependencias
  científicas a la imagen de producción.
- El generador escribe a `data/` con rutas relativas al CWD → mismo arreglo que
  ya se aplicó a `export_graph_diagram.py` (`Path(__file__).resolve().parents[1]`).

### Columnas reales

```
transactions:        transaction_id, customer_id, amount, currency, country,
                     chanel, device_id, timestamp, merchant_id, issuer_bank

customer_behavior:   customer_id, usual_amount_avg, usual_hours,
                     usual_countries, usual_devices, usual_channel,
                     account_creation_date, last_profile_update,
                     issuer_bank, daily_limit
```

Dos cosas que resuelve el **adaptador de seed**, no el schema: la columna se
llama **`chanel`** (typo heredado del reto original) y los **timestamps son
naive** (`2025-12-17T23:45:00`, sin offset).

---

## 3. Hechos medidos

Reproducidos con `seed(42)`. No son estimaciones.

### Integridad — limpia

- `transaction_id`: **7 000 únicos**, sin duplicados → la PK y el UNIQUE de
  `cases.transaction_id` no se rompen.
- `customer_id` huérfanos: **0**.
- 999 clientes distintos aparecen en transacciones, de 1 000 perfiles.

### Ventana temporal — partida

```
rango: 2025-03-12 00:10  →  2026-02-17 00:10

2025-03:     1
2025-11:    66
2025-12: 6 931
2026-01:     1
2026-02:     1
```

Las 69 fuera de diciembre son transacciones FP-10, que el generador fecha como
`last_profile_update + 10 minutos`, y ese campo se dispersa por todo 2025.

**Huella identificable**: **70 transacciones caen exactamente a las 00:10:00**,
de las cuales 67 están fuera de diciembre. Ninguna transacción real tendría esa
regularidad.

### Distribución

| Medición | Valor |
|---|---|
| Países en los perfiles | US 166 · CL 150 · AR 147 · CO 138 · PE 136 · ES 135 · MX 128 |
| Moneda | `PE → PEN` (956 tx), todo lo demás `→ USD` |
| Transacciones en RU (marcador de FP-02) | 49 |
| Comercio `M-999` (lista negra, FP-07) | 76 |
| Dispositivos `D-999xxx` (FP-02, FP-04) | 217 |
| Cuentas creadas después del 2025-11-01 | 90 |

### Políticas de secuencia — detectables

Las secuencias sobreviven al orden global del CSV:

| Política | Positivos detectables |
|---|---|
| FP-03 velocity (3+ tx / 5 min, mismo dispositivo) | 57 dispositivos |
| FP-05 geolocalización imposible (2 países / <2 h) | 76 clientes |
| FP-12 fraccionamiento (3+ pagos > límite diario) | 66 grupos |

### Solapamiento entre políticas

Medido **por la regla, no por la intención del generador**:

| Condición | Transacciones |
|---|---|
| FP-01 completa (monto > 3× **y** fuera de horario) | 68 |
| Solo monto > 3× | 169 |
| Solo fuera de horario | 171 |

Las ~100 transacciones con monto > 3× que no disparan FP-01 vienen de las ramas
FP-04, FP-06 y FP-09. **Una transacción puede satisfacer varias políticas** →
las etiquetas son múltiples, no únicas.

---

## 4. Tres supuestos del contrato que el dataset rompe

### 4.1 La zona horaria única

§2.7 dice: *"`usual_hours` es hora local → se asume `America/Lima` para v1 y se
documenta el supuesto"*. Razonable con dos clientes peruanos; falso con siete
países.

Para un cliente en Madrid, interpretar `09-22` como hora de Lima corre la
ventana **siete horas**: se evalúa `02-15`. FP-01 —"horario fuera de rango"—
queda mal evaluada para **6 de 7 países, el 86% de los clientes**.

**→ Resuelto en §6.1.** Enmienda para v0.4: ese supuesto muere.

### 4.2 El promedio del perfil no tiene moneda

`usual_amount_avg` es un número sin moneda; las transacciones sí la tienen.

**77 de 999 clientes tienen historial en dos monedas** —los que recibieron una
transacción FP-02 (Rusia, USD) o FP-05 (Perú/PEN + España/USD)—.

El efecto no es cosmético: un cliente peruano con promedio 1 935 PEN que recibe
una transacción de 1 935 **USD** aparece como 3.7× su promedio. **La conflación
de monedas fabrica falsos positivos de FP-01** justo en las transacciones que se
quiere evaluar.

**→ Resuelto en §6.2.**

### 4.3 Coherencia temporal

Las 69 transacciones fuera de diciembre hacen que cualquier consulta de
"historial reciente" se comporte distinto para ellas. Y la huella de las
00:10:00 es un artefacto que un modelo podría aprender.

**→ Corrección pedida al equipo de banca (§8).**

---

## 5. Lo que el dataset no ejercita

Cuatro decisiones **deliberadas** del contrato con **cero cobertura**. El
harness del entregable 7 no puede probar ninguna.

| Caso | Cobertura | Dónde se decidió |
|---|---|---|
| Cliente nocturno (`22-06`, `start > end`) | **0 / 1 000** | §2.5: *"`start > end` no está prohibido; la lógica debe contemplar el cruce de medianoche"* |
| `usual_devices` / `usual_countries` vacíos | **0 / 1 000** | §2.5: *"ningún dispositivo habitual significa que todo dispositivo es nuevo → eso es señal, no dato inválido"* |
| Cliente **sin perfil** | **0 / 999** | v0.3 enmienda #1: `CaseDetail.customer` pasó a nullable porque *"es el escenario que más importa"* |
| Perfil multi-país | 0 (`usual_countries` es un solo país) | §2.5: `list[str]` |

La ironía del tercero: la enmienda #1 de v0.3 se justificó diciendo que el
cliente sin perfil es el caso más sospechoso, y el dataset no tiene ninguno.

---

## 6. Decisiones tomadas, con su argumento

### 6.1 Zona horaria → columna `timezone` (IANA) en el perfil

El seed la deriva del país mientras la fuente no la traiga.

**Contra mantener `America/Lima`**: el error (7 h para Madrid) es mayor que la
tolerancia de la ventana. No es imprecisión, es evaluar otra cosa.

**Contra derivar del país en tiempo de lectura**: exacto para PE, CO, AR y CL,
pero **US abarca seis zonas y MX tres**. Elegir `America/New_York` para todos
los clientes estadounidenses mete hasta 3 h de error. El mapeo es una
aproximación, y una aproximación no debe vivir en el dominio disfrazada de dato.

**A favor de la columna**: el modelo queda correcto, `zoneinfo` maneja el
horario de verano solo —importa, porque ES y CL lo tienen y la ventana local se
corre una hora dos veces al año— y cuando la fuente traiga el campo real **el
dominio no cambia**: solo deja de aproximar el seed.

Es el patrón ya fijado: *"la normalización de formato vive en el script de seed;
un adaptador por fuente, el dominio recibe datos canónicos"*.

**Descartado**: guardar la ventana ya convertida a UTC. El horario de verano
hace que la conversión no sea constante (`09-22` en Madrid es `08-21` UTC en
invierno y `07-20` en verano) → hornearía un supuesto de estación.

### 6.2 Moneda → atributo de la cuenta, no del país de la transacción

Constante por cliente; el perfil declara su `currency`.

No es una simplificación: **corrige un error del generador**, que hace
`"PEN" if country == "PE" else "USD"`, o sea deriva la moneda del país del
evento. Una tarjeta no funciona así: un cliente peruano que compra en Madrid
genera un cargo que el emisor liquida **en la moneda de su cuenta**. El monto que
un motor de riesgo compara contra la línea base es el liquidado, no el nominal
extranjero.

Consecuencias:

- La comparación *monto vs promedio* es exacta siempre, **sin tabla de tipo de
  cambio**.
- **La dimensión internacional sobrevive intacta**: `country` sigue variando,
  que es lo que FP-02 y FP-05 necesitan.
- Es más realista, no menos.

Conviene asignarla por país de origen (`PE→PEN`, `ES→EUR`, `MX→MXN`, `US→USD`…)
en vez de unificar todo a USD: cuesta un diccionario y evita que el dataset
parezca sintético.

`currency` en el perfil **no es redundante** con el de la transacción: hace
`usual_amount_avg` autodescriptivo. Un número de dinero sin moneda es un número,
no un monto.

**Fuera de alcance, documentado**: cuentas multi-moneda y conversión FX.

### 6.3 Etiquetas de secuencia → en la transacción que cierra el patrón

Las anteriores quedan etiquetadas como aprobación correcta.

**El argumento decisivo**: el sistema evalúa **una transacción a la vez**.
`POST /cases` recibe una `Transaction`. Cuando llega la #4 de la ráfaga, el
agente mira atrás, ve tres en menos de 5 minutos y dispara. Cuando llegó la #1,
**ese patrón no existía todavía**: aprobarla era correcto con la información
disponible.

Etiquetar las cuatro haría que el harness espere una detección que requiere una
máquina del tiempo → falsos negativos que no son fallas del sistema, y recall
hundido por un artefacto de la etiqueta.

Las cuatro políticas de secuencia se comportan igual: cierra la cuarta en FP-03,
el monto grande en FP-04, la segunda en FP-05, y el tercer pago en FP-12 (los
dos primeros suman 0.8× el límite; el tercero lo cruza).

> La etiqueta responde *"¿qué debía decidir el sistema en ese instante?"*, no
> *"¿esto fue fraude, visto en retrospectiva?"*. Confundirlas es el error clásico
> al etiquetar datos de fraude.

**Columna adicional**: `fraud_group_id`, común a las transacciones de una misma
ráfaga. Habilita una métrica que el recall por fila no da: *"¿detectamos la
ráfaga, y en cuál de sus transacciones?"* — o sea cuánta pérdida ocurrió antes
de la detección. Para el entregable 7, que pide *"métricas apropiadas y
justificadas"*, una métrica a nivel de grupo junto a la precisión por fila es un
argumento fuerte, y sale de una columna.

---

## 7–8. Alcance y peticiones — **superadas**

El equipo de banca se retiró del curso. El generador y el catálogo pasaron a ser
nuestros, así que los ocho puntos del §8 dejaron de ser peticiones bloqueantes y
se volvieron ediciones a `scripts/generate_data.py`. Los ocho están aplicados.

El alcance final es **10 de 11 políticas** —FP-01…FP-09 y FP-11—, no 9. Con la
numeración corregida, la política que decía "promedio del segmento" es FP-08 y se
resolvió agregando `segment` al perfil. La excluida es **FP-10** (alerta pública
sobre el emisor/BIN), y por una razón distinta de la que se creía: no faltan
etiquetas, su evidencia es búsqueda web real y no es reproducible entre corridas.

Detalle y argumento: `enmiendas_pendientes.md` §1.3 y §2.4, y `data/README.md`.

---

## 9. Trabajo de la etapa

### 9.1 Campos nuevos

**`CustomerBehavior`**

| Campo | Tipo propuesto | Habilita |
|---|---|---|
| `usual_channel` | `Channel` | FP-06 |
| `account_creation_date` | `date` | FP-09 |
| `last_profile_update` | `datetime` aware | FP-10 |
| `issuer_bank` | `str` | FP-11 |
| `daily_limit` | `Decimal(12,2)` | FP-12 |
| `currency` | `str(3)` | decisión 6.2 |
| `timezone` | `str` IANA | decisión 6.1 |

**`Transaction`**: `issuer_bank` (`str`).

### 9.2 Índices de historial

Las políticas de secuencia consultan ventanas temporales:

| Índice | Para |
|---|---|
| `transactions (customer_id, timestamp)` | FP-05, FP-12, historial general |
| `transactions (device_id, timestamp)` | FP-03, FP-04 |

**Ojo**: `transactions` hoy tiene índice **solo en `customer_id`**. Al crear el
compuesto `(customer_id, timestamp)`, el índice suelto queda redundante —es un
prefijo por la izquierda— y conviene eliminarlo en la misma migración.

FP-12 filtra además por comercio; hay que medir si `(customer_id, timestamp)`
alcanza o si justifica `(customer_id, merchant_id, timestamp)`. Se decide con la
consulta escrita, no antes.

### 9.3 El seed

Normalizaciones que le tocan (patrón ya fijado: la normalización de formato vive
en el seed, no en el schema):

- `chanel` → `channel`
- `usual_hours` `"10-20"` → `(10, 20)`
- `usual_countries` `"MX"` → `["MX"]`
- `usual_devices` `"D-001"` → `["D-001"]`
- timestamp naive → aware UTC
- cuantizar montos a 2 decimales
- derivar `timezone` del país (aproximación explícita del adaptador)
- perfiles antes que transacciones

### 9.4 Plan de commits tentativo

```
feat(data): add synthetic dataset and its generator
feat(db): add behavioral profile fields for policy evaluation
feat(db): add composite indexes for transaction history queries
feat(data): seed the database from the synthetic dataset
test(data): verify the seed normalizes and loads correctly
```

Cada uno de los dos `feat(db)` sigue el patrón de siempre: schema Pydantic →
ORM → `alembic revision --autogenerate` → **leer la migración** → `upgrade head`
→ verificar con `\d+`.

### 9.5 El seed tiene dos destinos

Hasta ahora sembrar era "poblar mi local". Con la base compartida, el mismo
script escribe en un entorno donde otra persona está mirando. Eso le impone tres
requisitos que no tendría si fuera solo mío.

**Idempotente, no destructivo.** Un seed que solo inserta revienta al segundo
intento por `transaction_id` duplicado. Uno que trunca borra los casos que el
dashboard estaba renderizando. La pregunta de §10.3 deja de ser una preferencia
de estilo y pasa a ser un requisito de convivencia.

**Destino explícito, nunca implícito.** El script imprime a qué host apunta
—enmascarando credenciales— antes de escribir una sola fila, y escribir en la
compartida exige un flag deliberado. El accidente es barato de cometer: una
variable exportada que sobrevivió en la terminal basta para que un `seed` de
prueba aterrice en RDS. Y en la compartida deshacerlo no es `docker compose down -v`.

**Separar cargar historial de crear casos.** Las 7 000 transacciones son
historial que las políticas de secuencia necesitan (§10.2), pero el dashboard
necesita **casos con decisión** para pintar la cola HITL, no transacciones
sueltas. Son dos operaciones con destinatarios distintos y conviene que sean dos
comandos, no uno.

> Quién siembra la compartida y con qué aviso es frontera, no implementación:
> queda en `enmiendas_pendientes.md` §2.6 junto con las migraciones y el
> `downgrade`.

---

## 10. Preguntas abiertas para el chat nuevo

> **Estado**: 10.1 (`usual_channel` singular), 10.3 (idempotencia del seed) y
> 10.5 (qué tablas de seed entran en esta etapa) están decididas en
> `enmiendas_pendientes.md` §1.8, §1.9 y §2.1. El resto sigue abierto.

1. **`usual_channel` singular o `usual_channels: list[Channel]`?** El dataset
   trae uno, pero `usual_countries` y `usual_devices` son listas. La
   inconsistencia puede ser correcta —un cliente tiene un canal preferido y
   varios dispositivos— o puede ser un artefacto del generador.

2. **Fuga temporal en el historial.** Con las políticas de secuencia,
   `transactions` cumple **doble función**: es la fuente de casos *y* el
   historial que los agentes consultan. Si se cargan las 7 000 y se analiza una
   transacción de noviembre, el agente vería transacciones de diciembre — el
   futuro. El agente de secuencias **debe filtrar `timestamp < timestamp de la
   transacción analizada`**, no solo "reciente". Es un requisito, no una
   optimización, y el harness tiene que respetarlo o sus métricas son optimistas.

3. **Idempotencia del seed.** `transaction_id` es PK: correrlo dos veces
   revienta. Con la base compartida, *truncate* y recarga queda descartado —borra
   trabajo ajeno— así que la elección real es entre `ON CONFLICT DO NOTHING` y
   *upsert*. La distinción importa: el primero trata el dataset como inmutable
   —lo que ya está, está—; el segundo permite corregirlo cuando el equipo de
   banca entregue la versión con etiquetas (§8), que va a pasar. Precedente
   cercano y opuesto: el nodo persistidor eligió **reemplazo del agregado**
   (DELETE + INSERT), pero ahí el dueño del agregado es uno solo y el reintento
   es substitutivo por diseño. Acá hay dos escritores.

4. **¿Cuántos casos se analizan?** Las 7 000 son historial necesario para las
   secuencias, pero correr el grafo completo con llamadas a LLM sobre 7 000
   transacciones es caro y lento. Hay que separar *cargar historial* de *crear
   casos*, y decidir el muestreo para la demo y para el harness.

   La base compartida le pone número al muestreo: mi compañero necesita casos
   suficientes para que la cola tenga paginación real y variedad de `status` y
   `decision` —incluidos `PENDING_HUMAN` y `FAILED`, que son los que ejercitan la
   UI que más importa—. Eso se puede lograr sin correr el grafo completo:
   sembrar casos con decisiones fabricadas es más barato y más controlable que
   generarlos con LLM. La pregunta se parte en dos: **cuántos casos reales** para
   el harness, y **cuántos casos de utilería** para desbloquear el dashboard.

5. **Tabla de comercios en lista negra** (FP-07) y **`web_search_allowlist`**
   (§4 del contrato, la única tabla que aún no existe): ¿entran en esta etapa
   —son datos de seed— o en la de los agentes que las consumen?

6. **Enmiendas que esta etapa aporta a v0.4**: muerte del supuesto
   `America/Lima` (§2.7), `currency` y `timezone` en `CustomerBehavior` (§2.5),
   y los campos nuevos del perfil. Se acumulan en `enmiendas_pendientes.md`.

---

## 11. Ciclo de vida de este documento

Temporal, como `enmiendas_pendientes.md`. Al cerrar la etapa se disuelve en:

- **`docs/reviews/03-dataset-y-seed.md`** — el acta de la etapa.
- **Dos o tres ADR** — las decisiones de §6 tienen alternativa nombrada y
  descartada, que es el criterio de la plantilla: zona horaria como columna,
  moneda como atributo de cuenta, y etiqueta en la transacción que cierra el
  patrón.
- **`enmiendas_pendientes.md`** — lo que va al contrato v0.4.

Después se borra. Git lo conserva.
