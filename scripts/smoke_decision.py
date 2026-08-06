"""El primer caso que llega a `DECIDED`. Gate del paso 3.

    uv run python scripts/smoke_decision.py

Hasta esta etapa ningún caso podía decidirse solo: sin `citations_internal` el
invariante mandaba todo a `ESCALATE_TO_HUMAN`, y con él los entregables 7 y 8.
Esto verifica que el bloqueo se levantó, y verifica las tres cosas que podrían
haberlo levantado mal.

Requiere `seed.py` corrido —el índice tiene que existir— y `GEMINI_API_KEY` para
el escenario 2.

## Los tres escenarios

| # | Situación | Qué prueba |
|---|---|---|
| 1 | Ninguna política dispara | Que `APPROVE` es alcanzable: el 90% del tráfico |
| 2 | Dispara FP-03 | Que un veredicto autónomo cita la norma que lo autoriza |
| 3 | Dispara FP-03 y el proveedor de embeddings está caído | Que el veredicto sobrevive sin descubrimiento |
| 4 | El caso limpio, con una alerta sobre su emisor | Que la inteligencia externa cambia un veredicto, no sólo la confianza (ADR-0015) |

El tercero es el que justifica el diseño del nodo. Si `@degrades` fuera la única
red, una caída del proveedor se llevaría también el bloque de autorización y
todos los casos escalarían — lo contrario de lo que ADR-0011 promete. Correrlo
sobre el mismo caso que el escenario 2 prueba de paso la semántica de reemplazo
del agregado: un reintento sustituye, no acumula.

El cuarto reutiliza el caso **limpio** del escenario 1 por el mismo motivo: si
fuera un caso nuevo, "cambió de APPROVE a CHALLENGE" sería sólo una afirmación
sobre dos casos distintos. Reprocesar el mismo `case_id` con un indicador nuevo
es la demostración real —y de paso, otra vez reemplazo del agregado, no
acumulación.

## Por qué el cliente no tiene perfil

Para no sembrar un `CustomerBehavior`, que obligaría a este script a conocer la
forma completa del perfil. FP-03 no la necesita: sus insumos son la transacción y
el historial del dispositivo. El efecto lateral es que emite
`NO_CUSTOMER_PROFILE`, lo cual es útil: esa señal está excluida de la query
—describe la evidencia, no la transacción—, así que el escenario 1 termina con
señales y sin query, que es exactamente el caso que hace que `APPROVE` tenga que
ser alcanzable sin citar nada.
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import delete, select

from multiagent_fraud_detection.db.models import Case, Decision, ThreatIndicator, Transaction
from multiagent_fraud_detection.db.session import AsyncSessionLocal
from multiagent_fraud_detection.enums import CaseStatus, Channel, DecisionType, IndicatorType
from multiagent_fraud_detection.graph.builder import build_graph
from multiagent_fraud_detection.graph.context import GraphContext
from multiagent_fraud_detection.graph.nodes import POLICY_RAG, THREAT_INTEL
from multiagent_fraud_detection.intel.snapshot import SNAPSHOT_VERSION
from multiagent_fraud_detection.schemas.transaction import TransactionIn

CASO_LIMPIO = UUID("00000000-0000-0000-0000-0000000000d1")
CASO_BLOQUEO = UUID("00000000-0000-0000-0000-0000000000d2")

TX_LIMPIA = "T-SMOKE-DEC-CLEAN"
TX_BLOQUEO = "T-SMOKE-DEC-BURST-4"
TX_PREVIAS = [f"T-SMOKE-DEC-BURST-{i}" for i in (1, 2, 3)]

CLIENTE = "CU-SMOKE-DEC"
DISPOSITIVO = "D-SMOKE-DEC"
COMERCIO = "M-SMOKE-DEC"  # deliberadamente NO en la lista negra
BASE = datetime(2026, 3, 1, 14, 0, tzinfo=UTC)


class ProveedorCaido:
    """Un `Embedder` que siempre falla. El escenario 3."""

    def embed(self, text: str) -> list[float]:
        raise ConnectionError("el proveedor de embeddings no responde")


def tx(
    tx_id: str, *, minuto: int, monto: str, device: str, issuer_bank: str | None = None
) -> TransactionIn:
    return TransactionIn(
        transaction_id=tx_id,
        customer_id=CLIENTE,
        amount=Decimal(monto),
        currency="PEN",
        country="PE",
        channel=Channel.WEB,
        device_id=device,
        timestamp=BASE + timedelta(minutes=minuto),
        merchant_id=COMERCIO,
        issuer_bank=issuer_bank,
    )


# Emisor del caso limpio. Sin indicador sembrado no cambia nada del escenario
# 1 —`issuer_under_alert` no dispara sin una alerta que mirar—; el escenario 4
# lo reutiliza para demostrar que sembrar una sí lo hace.
EMISOR_SMOKE = "SMOKE-BANK"

TRANSACCIONES = {
    TX_LIMPIA: tx(
        TX_LIMPIA, minuto=0, monto="50.00", device="D-SMOKE-OTRO",
        issuer_bank=EMISOR_SMOKE,
    ),
    **{
        t: tx(t, minuto=10 + i, monto="60.00", device=DISPOSITIVO)
        for i, t in enumerate(TX_PREVIAS)
    },
    # Cuarta del mismo dispositivo dentro de la ventana de 5 minutos: con las
    # tres anteriores completa el `min_count=4` de FP-03.
    TX_BLOQUEO: tx(TX_BLOQUEO, minuto=13, monto="60.00", device=DISPOSITIVO),
}


async def limpiar() -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                delete(Case).where(Case.case_id.in_([CASO_LIMPIO, CASO_BLOQUEO]))
            )
            await session.execute(
                delete(Transaction).where(
                    Transaction.transaction_id.in_(list(TRANSACCIONES))
                )
            )
            await session.execute(
                delete(ThreatIndicator).where(ThreatIndicator.value == EMISOR_SMOKE)
            )


async def sembrar() -> None:
    await limpiar()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for t in TRANSACCIONES.values():
                session.add(Transaction(**t.model_dump()))
            session.add(
                Case(
                    case_id=CASO_LIMPIO,
                    transaction_id=TX_LIMPIA,
                    status=CaseStatus.ANALYZING,
                )
            )
            session.add(
                Case(
                    case_id=CASO_BLOQUEO,
                    transaction_id=TX_BLOQUEO,
                    status=CaseStatus.ANALYZING,
                )
            )


async def leer(case_id: UUID) -> tuple[Case, Decision | None]:
    """Relee desde una sesión nueva: fuerza el SELECT, no el identity map."""
    async with AsyncSessionLocal() as session:
        caso = await session.scalar(select(Case).where(Case.case_id == case_id))
        decision = await session.scalar(
            select(Decision).where(Decision.case_id == case_id)
        )
        return caso, decision


def mostrar(titulo: str, caso: Case, decision: Decision | None) -> None:
    print(f"\n{titulo}")
    print(f"   status              : {caso.status.value}")
    if decision is None:
        print("   (sin fila en decisions)")
        return
    print(f"   decision            : {decision.decision.value}")
    print(f"   matched_policies    : {decision.matched_policies}")
    print(f"   citations_internal  : "
          f"{[c['policy_id'] for c in decision.citations_internal]}")
    print(f"   risk / confidence   : {decision.risk_score} / {decision.confidence}")
    print(f"   degraded_agents     : {decision.degraded_agents}")
    print(f"   índice sellado      : {decision.retrieval_index_version}")
    print(f"   snapshot sellado    : {decision.threat_intel_version}")


async def main() -> int:
    problemas: list[str] = []
    await sembrar()
    graph = build_graph()
    contexto = GraphContext(session_factory=AsyncSessionLocal)

    # --- 1. ninguna política dispara --------------------------------------- #
    await graph.ainvoke(
        {"case_id": CASO_LIMPIO, "transaction": TRANSACCIONES[TX_LIMPIA]},
        context=contexto,
    )
    caso, decision = await leer(CASO_LIMPIO)
    mostrar("1. transacción sin políticas disparadas", caso, decision)

    if decision is None:
        problemas.append("el caso limpio no dejó fila en `decisions`")
    else:
        if decision.decision is not DecisionType.APPROVE:
            problemas.append(
                f"sin políticas disparadas se esperaba APPROVE y llegó "
                f"{decision.decision.value}"
            )
        if caso.status is not CaseStatus.DECIDED:
            problemas.append(f"el caso limpio quedó en {caso.status.value}")
        if decision.matched_policies:
            problemas.append(
                f"la transacción limpia disparó {decision.matched_policies}; "
                f"revisá los datos del fixture, no el invariante"
            )
        if decision.citations_internal:
            problemas.append(
                "hubo citas sin política disparada: la query debería haber salido "
                "vacía y el descubrimiento no debería haber corrido"
            )

    # --- 2. dispara FP-03 --------------------------------------------------- #
    await graph.ainvoke(
        {"case_id": CASO_BLOQUEO, "transaction": TRANSACCIONES[TX_BLOQUEO]},
        context=contexto,
    )
    caso, decision = await leer(CASO_BLOQUEO)
    mostrar("2. ráfaga de cuatro en el mismo dispositivo", caso, decision)

    if decision is None:
        problemas.append("el caso de bloqueo no dejó fila en `decisions`")
    else:
        citadas = {c["policy_id"] for c in decision.citations_internal}
        if "FP-03" not in (decision.matched_policies or []):
            problemas.append(
                "FP-03 no disparó: la ráfaga no quedó dentro de la ventana"
            )
        elif "FP-03" not in citadas:
            problemas.append("FP-03 disparó y no está citada: el invariante falló")
        if decision.decision is not DecisionType.BLOCK:
            problemas.append(
                f"FP-03 prescribe BLOCK y llegó {decision.decision.value}"
            )
        if caso.status is not CaseStatus.DECIDED:
            problemas.append(f"el caso de bloqueo quedó en {caso.status.value}")
        if len(citadas) <= 1:
            print("   nota: el descubrimiento no agregó políticas más allá de la "
                  "autorización")

    # --- 3. el mismo caso, con el proveedor caído --------------------------- #
    caido = GraphContext(
        session_factory=AsyncSessionLocal, embedder=ProveedorCaido()
    )
    await graph.ainvoke(
        {"case_id": CASO_BLOQUEO, "transaction": TRANSACCIONES[TX_BLOQUEO]},
        context=caido,
    )
    caso, decision = await leer(CASO_BLOQUEO)
    mostrar("3. la misma ráfaga con el proveedor de embeddings caído", caso, decision)

    if decision is None:
        problemas.append("con el proveedor caído no quedó fila en `decisions`")
    else:
        citadas = {c["policy_id"] for c in decision.citations_internal}
        if decision.decision is not DecisionType.BLOCK:
            problemas.append(
                f"el veredicto no sobrevivió a la caída del proveedor: "
                f"{decision.decision.value}"
            )
        if "FP-03" not in citadas:
            problemas.append(
                "el bloque de autorización no sobrevivió a la caída: es lo que "
                "el `try` interno del nodo existe para evitar"
            )
        if citadas != {"FP-03"}:
            problemas.append(
                f"hubo descubrimiento con el proveedor caído: {sorted(citadas)}"
            )
        if POLICY_RAG not in decision.degraded_agents:
            problemas.append(
                "la caída no quedó registrada en `agent_errors`: el Arbiter y el "
                "monitoreo no pueden saber que la evidencia estaba incompleta"
            )

    # --- 4. el caso limpio, con una alerta sobre su emisor ------------------ #
    #
    # El `case_id` es el mismo del escenario 1: `persist_decision` reemplaza el
    # agregado, así que la fila de `decisions` que va a quedar es esta, no una
    # unión con la del escenario 1.
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                ThreatIndicator(
                    indicator_type=IndicatorType.ISSUER,
                    value=EMISOR_SMOKE,
                    # Tres horas antes del cargo: dentro de la ventana de 24h de
                    # FP-10, y as-of contra `timestamp` — nunca contra `now()`.
                    observed_at=TRANSACCIONES[TX_LIMPIA].timestamp - timedelta(hours=3),
                    retrieved_at=datetime.now(UTC),
                    source_url="https://sbs.gob.pe/alertas/smoke-decision",
                    summary="Alerta simulada del smoke (no es una alerta real)",
                    snapshot_version=SNAPSHOT_VERSION,
                    added_by="smoke",
                )
            )

    # La caché de indicadores del contexto ya sirvió un lookup vacío durante el
    # escenario 1 y puede seguir vigente por su TTL. `invalidate()` es lo que
    # hace que el alta de arriba se vea al instante, en vez de esperar a que
    # venza — el mismo mecanismo que usaría el alta desde el dashboard.
    contexto.indicators.invalidate()

    await graph.ainvoke(
        {"case_id": CASO_LIMPIO, "transaction": TRANSACCIONES[TX_LIMPIA]},
        context=contexto,
    )
    caso, decision = await leer(CASO_LIMPIO)
    mostrar("4. el caso limpio, con una alerta sobre su emisor", caso, decision)

    if decision is None:
        problemas.append("con la alerta sembrada no quedó fila en `decisions`")
    else:
        citadas = {c["policy_id"] for c in decision.citations_internal}
        if decision.decision is not DecisionType.CHALLENGE:
            problemas.append(
                f"FP-10 prescribe CHALLENGE y llegó {decision.decision.value}"
            )
        if "FP-10" not in (decision.matched_policies or []):
            problemas.append(
                "FP-10 no disparó: revisá que el indicador haya quedado dentro "
                "de la ventana de 24h"
            )
        elif "FP-10" not in citadas:
            problemas.append("FP-10 disparó y no está citada: el invariante falló")
        if not decision.citations_external:
            problemas.append(
                "FP-10 disparó sin dejar cita externa: el analista no podría "
                "ver de qué fuente salió la alerta"
            )
        if decision.threat_intel_version is None:
            problemas.append(
                "threat_intel_version quedó nulo con el nodo corriendo limpio: "
                "un veredicto que sí consultó el snapshot tiene que sellarlo"
            )
        if THREAT_INTEL in decision.degraded_agents:
            problemas.append("el nodo de inteligencia externa degradó sin motivo")

    print()
    if problemas:
        print(f"FALLA: {len(problemas)} problemas")
        for p in problemas:
            print(f"  - {p}")
        return 1

    # Limpieza al final, no sólo al principio de la próxima corrida: `TX_LIMPIA`
    # lleva `issuer_bank`, y dejarlo en `transactions` filtraría hacia
    # `fetch_threat_intel.py` —que arma su lista de emisores con un `SELECT
    # DISTINCT issuer_bank`— y una corrida real pagaría una búsqueda por un
    # emisor que no existe. El resto de los datos del smoke no tiene ese
    # efecto lateral, pero limpiar todo junto es más simple que separar cuál sí.
    await limpiar()

    print("OK · un caso aprobado y uno bloqueado, los dos en DECIDED")
    print("     el veredicto sobrevive a que el proveedor de embeddings caiga")
    print("     una alerta externa cambia el veredicto del caso limpio, no sólo la confianza")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    finally:
        pass
