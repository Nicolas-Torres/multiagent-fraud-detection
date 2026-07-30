# Enmiendas pendientes — Contrato de Interfaz

**Estado**: acumulando hacia v0.5. Se consolidan en `contrato_de_interfaz.md` al
cerrar la etapa de **dataset y seed**.

> Documento de trabajo: se **vacía** al publicar una versión, no se archiva.
> Nunca hay dos. Vigente: v0.4.
>
> Contexto completo de esta etapa: [`briefing_dataset.md`](briefing_dataset.md).

---

## 1. Decididas — listas para redactar

| # | Enmienda | Toca |
|---|---|---|
| 1 | Muere el supuesto `America/Lima` | §2.7 |
| 2 | `CustomerBehavior` gana `currency` y `timezone` | §2.5 |
| 3 | `CustomerBehavior` gana cinco campos de evaluación de políticas | §2.5 |
| 4 | `Transaction` gana `issuer_bank` | §2.5 |
| 5 | Índices de historial en `transactions` | §7 |

### 1.1 — Muere el supuesto de zona horaria única

§2.7 de v0.4 ya lo marca como 🔶. El dataset tiene **siete países**; interpretar
la ventana horaria de un cliente en Madrid como hora de Lima la corre siete horas
y evalúa otra cosa. Afecta al 86% de los clientes.

**Resolución**: `timezone` (IANA) como columna del perfil. El seed la deriva del
país mientras la fuente no la traiga —una aproximación del adaptador, no del
dominio—. Derivarla en tiempo de lectura no sirve: US abarca seis zonas y MX tres.

Descartado guardar la ventana ya convertida a UTC: el horario de verano hace que
la conversión no sea constante, y hornearía un supuesto de estación.

### 1.2 — La moneda es atributo de la cuenta

`usual_amount_avg` es hoy un número sin moneda. Con el dataset, 77 de 999 clientes
tienen historial en dos monedas, y comparar "3x el promedio" entre ellas fabrica
falsos positivos.

**Resolución**: `currency` en el perfil, constante por cliente. No es una
simplificación: una tarjeta liquida en la moneda de la cuenta, no en la del país
donde ocurre la compra. La dimensión internacional sobrevive intacta porque
`country` sigue variando.

Fuera de alcance, documentado: cuentas multi-moneda y conversión FX.

### 1.3 — Campos nuevos del perfil

| Campo | Habilita |
|---|---|
| `usual_channel` | FP-06 canal nuevo con monto alto |
| `account_creation_date` | FP-09 cuenta nueva |
| `last_profile_update` | FP-10 cambio de datos + transacción inmediata |
| `issuer_bank` | FP-11 alerta sobre emisor |
| `daily_limit` | FP-12 fraccionamiento |

### 1.4 — Índices de historial

Cuatro políticas (FP-03, 04, 05, 12) evalúan **secuencias**, no transacciones
sueltas. Necesitan `transactions (customer_id, timestamp)` y
`(device_id, timestamp)`.

Al crear el compuesto, el índice suelto en `customer_id` queda redundante —es un
prefijo por la izquierda— y se elimina en la misma migración.

---

## 2. Abiertas — bloquean la redacción de v0.5

### 2.1 — ¿`usual_channel` singular o lista?

El dataset trae uno, pero `usual_countries` y `usual_devices` son listas. Puede
ser correcto —un cliente tiene un canal preferido y varios dispositivos— o un
artefacto del generador.

### 2.2 — Fuga temporal en el historial

Con las políticas de secuencia, `transactions` cumple **doble función**: fuente de
casos e historial que los agentes consultan. El agente de secuencias **debe**
filtrar `timestamp < timestamp de la transacción analizada`, no solo "reciente",
o vería el futuro. Es un requisito de corrección; si el harness no lo respeta, sus
métricas salen optimistas.

¿Se documenta en el contrato o queda como regla de implementación del agente?

### 2.3 — ¿`CaseSummary` gana `risk_score`?

La cola HITL hoy muestra `decision` y `confidence`. Para triaje, ordenar por
riesgo es más útil que por confianza: el analista quiere ver primero lo más
sospechoso, no lo más incierto.

No se decidió al redactar v0.4 —se dejó fuera para no ampliar el alcance sin
discutirlo—. Es una columna en una proyección plana, barata en cualquier momento.

### 2.4 — Ground truth incompleto

El dataset no trae etiquetas y hay que pedirlas (§8 del briefing). Además:

- **FP-11 no puede tener ground truth**: el generador asigna el banco del propio
  cliente, así que no hay forma de identificar sus positivos.
- **FP-09 dice "promedio del segmento"** y solo existe el promedio del cliente.
  Viable redefiniéndolo, con la desviación documentada.
- **Las únicas etiquetas humanas** que produce el sistema vienen de casos
  escalados —por construcción, los ambiguos—: ground truth sesgado por muestreo.

Las tres van a Limitaciones (entregable 7), no al contrato. Se anotan acá para no
perderlas.

### 2.5 — Fórmula de `base_confidence` y `risk_score`

v0.4 define **qué significan** y **en qué dirección se mueven**; no define los
pesos por severidad, la función de agregación ni el delta máximo que el Arbiter
puede aplicar. Eso vive dentro de `evidence_aggregation` y necesita el catálogo de
`code`, que no existe.

No toca el schema: `scoring_version` ya está previsto justamente para que la
fórmula pueda cambiar sin invalidar lo persistido.

---

## 3. Hallazgos que **no** tocan el contrato

Van al repaso de etapa. Se anotan acá para no perderlos.

- **Cero aristas condicionales** en el grafo: `DECIDED` vs `PENDING_HUMAN` es un
  valor de `status` que escribe un mismo nodo, no una bifurcación.
- **Atomicidad del superstep**: si un nodo paralelo lanza, se pierden también los
  aportes de sus hermanos y el grafo aborta. Verificado con un grafo mínimo. De
  ahí que los nodos de evidencia **nunca lancen**.
- **Reintentos adentro del nodo**, no vía `RetryPolicy`: son incompatibles, porque
  un nodo que captura su excepción nunca deja que la política dispare.
- **Sin checkpointer**: solo cubriría la muerte del proceso, más barato con una
  consulta sobre casos estancados en `ANALYZING`. Recomendación del entregable 10.
- **Dependencias de runtime por `context_schema`**, no por import global: tres
  nodos necesitarán la base (perfil, secuencias, persistencia) y el import global
  ataría cualquier import del módulo a que haya base configurada.
- **Un test no es dueño de la base**: contar filas globalmente lo vuelve
  dependiente del orden de ejecución. Filtrar siempre por la clave del caso.