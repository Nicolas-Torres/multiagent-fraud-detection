# Notas — tiempo real: autorización en línea vs. investigación del caso

> **No es un cierre de etapa**, así que no lleva número de la secuencia. Recoge
> una duda que surgió al redactar la publicación de la demo, la aclaración y
> lo que se cambió por ella: el desvío D-08 en `docs/trazabilidad.md`.
> Fecha: 2026-10-02.

---

## 1. La duda

> *"Cuando le transfiero dinero a un amigo, la transferencia se hace al instante:
> mi amigo recibe el dinero y puede usarlo. En este proyecto el análisis tarda
> entre 15 y 22 segundos. Eso no me cuadra."*

La duda es correcta. Si el sistema se lee como el que **autoriza** la
transferencia, 12 a 22 segundos son inaceptables. Un banco aprueba o rechaza un
pago en milisegundos.

Apareció al poner la latencia como KPI en el borrador del post. La frase "la
API responde al instante y analiza en segundo plano" sugería que el pago espera
al análisis, y no es así.

---

## 2. La aclaración: la detección de fraude trabaja en dos capas

| Capa | Cuándo | Cuánto tarda | Qué usa | Qué decide |
|---|---|---|---|---|
| **1. En línea** (autorización) | Antes de mover el dinero | Milisegundos (~100–300 ms) | Reglas y un modelo de ML rápido (por ejemplo, gradient boosting) | Aprobar, rechazar o pedir verificación (OTP, biometría) |
| **2. Investigación** (posterior) | Después, con el caso registrado | Minutos a días | Reglas más profundas, contexto, analistas humanos | Congelar la cuenta destino, revertir, contactar al cliente, cerrar el caso |

En una transferencia inmediata (Yape, Plin, CCE), la capa 1 decide en
milisegundos y el dinero llega al instante. La capa 2 sigue después: si el
destino resulta ser una cuenta "mula", el banco la congela horas más tarde.

**Un LLM no cabe en la capa 1.** Una sola llamada tarda segundos y su latencia
varía. Ningún banco lo pondría en el camino de una autorización.

---

## 3. Dónde encaja este proyecto

En la **capa 2**, y la arquitectura ya tiene esa forma:

- `POST /cases` registra la transacción y responde `202` (contrato §2.3). No
  bloquea a nadie esperando el veredicto.
- El grafo analiza aparte: reglas, RAG de políticas, debate, árbitro y
  explicación.
- Lo que no alcanza confianza pasa a la cola HITL, para un analista.

Es el flujo de un sistema de gestión de casos, o de un copiloto del analista.
Leídos así, los veredictos tienen sentido operativo: `BLOCK` es "congelar o
revertir", `CHALLENGE` es "contactar al cliente para verificar" y
`ESCALATE_TO_HUMAN` es "un analista decide".

**El hueco:** el enunciado pide "analizar transacciones en tiempo real" y
"decisiones rápidas", y hasta hoy eso no estaba declarado como desvío.
Dependía de que alguien lo explicara en voz alta.

---

## 4. Lo medido

LangSmith, producción, ventana de 3 días al 2026-10-01 (38 decisiones):

| Nodo | Latencia promedio | ¿LLM? |
|---|---|---|
| `transaction_context` | 0,10 s | no |
| `behavioral_pattern` | 0,15 s | no |
| `external_threat_intel` | 0,11 s | no |
| `internal_policy_rag` | 1,64 s | no (embeddings de Gemini) |
| `evidence_aggregation` | 0,001 s | no |
| `debate_pro_fraud` | 4,85 s | sí |
| `debate_pro_customer` | 5,55 s | sí |
| `decision_arbiter` | 4,24 s | sí |
| `explainability` | 2,40 s | sí |
| `persist_decision` | 0,18 s | no |
| **Decisión completa** | **p50 12,4 s · p99 22,1 s** | 4 llamadas |

Los tres primeros corren en paralelo, así que **las reglas se resuelven en
~0,15 s**. Casi todo el tiempo restante es de los cuatro LLM y del embedding del
RAG.

---

## 5. Lo que iría en línea ya está separado en el diseño

El veredicto final se decide sobre un **piso** determinístico,
`prescribed_action(catalog, matched_policies)`. Sale sólo de las políticas que
dispararon las reglas, y el LLM puede subirlo pero nunca bajarlo (ADR-0006,
ADR-0016). La guarda vuelve a verificarlo en `persist_decision`.

Ese piso es exactamente lo que una capa 1 necesitaría: determinístico, auditable
y rápido. Hoy, sin embargo, **se calcula recién dentro de `decision_arbiter`**,
después del RAG y del debate, y la API no lo expone antes.

Para que el sistema cubra también la capa 1 harían falta:

1. Calcular el piso apenas terminan las reglas (superstep 0) y devolverlo como
   **decisión provisional**: en el `202`, o en un endpoint propio.
2. Un ADR y una enmienda al contrato: es un campo o un endpoint nuevo en la
   frontera.
3. En un despliegue real, un modelo de ML rápido junto a las reglas. El dataset
   sintético no alcanza para entrenarlo con sentido (mismo argumento que D-04).

No se implementa ahora: el proyecto queda declarado como capa 2.

---

## 6. Qué se cambió

- **`docs/trazabilidad.md`, desvío D-08**: el sistema cubre la investigación del
  caso, no la autorización en línea, con la razón y lo que falta.
- **Publicación de LinkedIn**: la latencia deja de presentarse como si el pago
  esperara al análisis. Si va como KPI, va con contexto: "análisis completo con
  4 LLM: p50 12,4 s, pensado para revisión de casos, no para autorizar el pago
  en línea".

## 7. Para una entrevista

> *"Esto es la capa de investigación, no la de autorización. En línea irían las
> reglas y un modelo rápido, en milisegundos. El LLM entra después, donde 15
> segundos no importan y la explicación sí. Y el diseño ya separa el piso
> determinístico, que es lo que iría en línea: el LLM no puede bajarlo."*
