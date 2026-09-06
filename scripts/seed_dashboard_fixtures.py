"""Datos de desarrollo para el dashboard: casos completos, insertados directo
en Postgres, sin correr el grafo.

**No es `seed.py`.** `seed.py` carga historial —transacciones y perfiles—, no
casos: "crear un caso es correr el pipeline", dice su propio docstring, y deja
el muestreo para la demo a un script aparte. Este es ese script.

Ningún proveedor de LLM interviene: veredictos, señales, citas, debate y texto
de auditoría/cliente son fijos a mano y llevan la marca `[dato de desarrollo]`
—mismo criterio que `FakeJudge`/`FakeNarrator`: un doble de prueba lleva su
propia versión, para que no se confunda con un veredicto real—. Es lo que
permite **garantizar** la cobertura que el dataset real no puede prometer:
los 6 `CaseStatus`, los 4 `DecisionType`, un caso con `customer: null` y uno
con `degraded_agents` no vacío.

Las transacciones y perfiles de base sí son reales —filas de
`data/transactions.csv` / `data/customer_behaviors.csv`, vía el mismo
adaptador que usa `seed.py`— para que montos, países y monedas se vean
auténticos y no genéricos.

Idempotente: identifica sus propios casos por `transaction_id` y los
reemplaza por completo en cada corrida, igual que W2 con el caso real
(§7.3 del contrato: "un reintento sustituye, no complementa").

    uv run python scripts/seed_dashboard_fixtures.py
"""

import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from _dataset import leer_perfiles, leer_transacciones
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from multiagent_fraud_detection.db.models import (
    AgentError,
    Case,
    CustomerBehavior,
    Decision,
    HumanResolution,
    Signal,
    Transaction,
)
from multiagent_fraud_detection.db.session import AsyncSessionLocal
from multiagent_fraud_detection.enums import (
    CaseStatus,
    DecisionType,
    HumanAction,
    Severity,
)
from multiagent_fraud_detection.schemas.customer_behavior import CustomerBehaviorIn
from multiagent_fraud_detection.schemas.transaction import TransactionIn

FIX = "[dato de desarrollo]"

# `binding_set_version` real de `data/policies/policy_bindings_2025.1.json` —
# para que `policy_catalog_version` se vea consistente con el catálogo de
# verdad, sin re-leer el archivo acá.
CATALOG_VERSION = "2025.1-b1"
DOC_VERSION = "2025.1"

FULL_ROUTE = [
    "transaction_context",
    "behavioral_pattern",
    "external_threat_intel",
    "internal_policy_rag",
    "evidence_aggregation",
    "debate_pro_fraud",
    "debate_pro_customer",
    "decision_arbiter",
    "explainability",
]
ROUTE_SIN_THREAT_INTEL = [a for a in FULL_ROUTE if a != "external_threat_intel"]

# policy_id -> (code, description, severity) de la señal que la dispara.
# Subconjunto del catálogo real (data/policies/fraud_policies_2025.1.json),
# elegido para cubrir los tres veredictos autónomos que sí exigen cita.
SIGNALS: dict[str, tuple[str, str, Severity]] = {
    "FP-01": (
        "AMOUNT_OUT_OF_RANGE",
        f"{FIX} Monto muy por encima del promedio habitual, fuera del horario usual.",
        Severity.MEDIUM,
    ),
    "FP-03": (
        "DEVICE_VELOCITY",
        f"{FIX} El mismo dispositivo superó el máximo de transacciones en la ventana.",
        Severity.HIGH,
    ),
    "FP-07": (
        "BLACKLISTED_MERCHANT",
        f"{FIX} El comercio tiene historial de fraude registrado.",
        Severity.HIGH,
    ),
    "FP-10": (
        "ISSUER_UNDER_ALERT",
        f"{FIX} Hay una alerta externa activa sobre el banco emisor.",
        Severity.MEDIUM,
    ),
}

DEBATE = {
    DecisionType.APPROVE: (
        f"{FIX} No hay evidencia que sostenga un argumento de fraude en este caso.",
        f"{FIX} El patrón de la transacción es coherente con el comportamiento habitual del cliente.",
    ),
    DecisionType.CHALLENGE: (
        f"{FIX} La combinación de señales se aparta del comportamiento habitual del cliente.",
        f"{FIX} El resto del perfil del cliente es consistente; podría ser un uso legítimo excepcional.",
    ),
    DecisionType.BLOCK: (
        f"{FIX} La señal disparada por sí sola ya justifica bloquear sin esperar confirmación.",
        f"{FIX} No hay contraargumento suficiente frente a una señal de esta severidad.",
    ),
    DecisionType.ESCALATE_TO_HUMAN: (
        f"{FIX} Hay indicios de riesgo, pero ninguno concluyente por sí solo.",
        f"{FIX} También hay elementos a favor del cliente; la evidencia no alcanza para decidir en automático.",
    ),
}

EXPLANATION_CUSTOMER = {
    DecisionType.APPROVE: f"{FIX} Tu transacción fue aprobada.",
    DecisionType.CHALLENGE: f"{FIX} Necesitamos que confirmes esta transacción antes de continuar.",
    DecisionType.BLOCK: f"{FIX} No pudimos procesar esta transacción.",
    DecisionType.ESCALATE_TO_HUMAN: f"{FIX} Tu transacción está en revisión manual.",
}

EXPLANATION_AUDIT = {
    DecisionType.APPROVE: f"{FIX} Ninguna política del catálogo se disparó. Evidencia completa, confianza alta.",
    DecisionType.CHALLENGE: f"{FIX} La política citada prescribe verificación adicional ante esta combinación de señales.",
    DecisionType.BLOCK: f"{FIX} La política citada prescribe bloqueo directo ante esta combinación de señales.",
    DecisionType.ESCALATE_TO_HUMAN: f"{FIX} Señales contradictorias entre sí: se deriva a un analista en vez de decidir en automático.",
}

# risk_score, confidence, base_confidence — por veredicto. La confianza tiene
# forma de U (contrato §2.5): alta en los extremos (APPROVE/BLOCK claros),
# baja en el medio (ESCALATE).
SCORES: dict[DecisionType, tuple[float, float, float]] = {
    DecisionType.APPROVE: (0.05, 0.95, 0.95),
    DecisionType.CHALLENGE: (0.55, 0.75, 0.75),
    DecisionType.BLOCK: (0.9, 0.92, 0.92),
    DecisionType.ESCALATE_TO_HUMAN: (0.5, 0.4, 0.4),
}


@dataclass(frozen=True)
class Spec:
    status: CaseStatus
    decision: DecisionType | None = None
    matched: tuple[str, ...] = ()
    con_citacion_externa: bool = False
    degradado: bool = False
    resolucion: HumanAction | None = None
    con_perfil: bool = True


# 27 casos: cobertura garantizada de los 6 `CaseStatus`, los 4 `DecisionType`,
# un `customer: null` y un `degraded_agents` no vacío — más volumen realista
# para que la Cola no se vea vacía. El orden es el de inserción; el timestamp
# se escalona en `_construir_caso` para que la Cola tenga una cronología
# creíble (`now()` de Postgres comparte instante dentro de una transacción).
SPECS: list[Spec] = [
    Spec(CaseStatus.RECEIVED),
    Spec(CaseStatus.ANALYZING),
    Spec(CaseStatus.FAILED),
    *[Spec(CaseStatus.DECIDED, DecisionType.APPROVE) for _ in range(10)],
    Spec(CaseStatus.DECIDED, DecisionType.APPROVE, con_perfil=False),
    *[Spec(CaseStatus.DECIDED, DecisionType.CHALLENGE, matched=("FP-01",)) for _ in range(3)],
    Spec(CaseStatus.DECIDED, DecisionType.CHALLENGE, matched=("FP-10",), con_citacion_externa=True),
    *[Spec(CaseStatus.DECIDED, DecisionType.BLOCK, matched=("FP-03",)) for _ in range(2)],
    Spec(CaseStatus.DECIDED, DecisionType.BLOCK, matched=("FP-07",)),
    Spec(CaseStatus.PENDING_HUMAN, DecisionType.ESCALATE_TO_HUMAN),
    Spec(CaseStatus.PENDING_HUMAN, DecisionType.ESCALATE_TO_HUMAN, degradado=True),
    Spec(CaseStatus.RESOLVED, DecisionType.ESCALATE_TO_HUMAN, resolucion=HumanAction.APPROVE),
    Spec(CaseStatus.RESOLVED, DecisionType.ESCALATE_TO_HUMAN, resolucion=HumanAction.REJECT),
]


async def _upsert_uno(session, modelo, valores: dict, pk: str) -> None:
    stmt = pg_insert(modelo).values(**valores)
    columnas = [k for k in valores if k != pk]
    stmt = stmt.on_conflict_do_update(
        index_elements=[pk], set_={c: getattr(stmt.excluded, c) for c in columnas}
    )
    await session.execute(stmt)


def _elegir_transacciones() -> tuple[list[TransactionIn], TransactionIn, dict[str, CustomerBehaviorIn]]:
    """De las filas reales del dataset: una sin perfil (para `customer: null`)
    y N con perfil, ambas en orden estable por `transaction_id`."""
    perfiles = {p.customer_id: p for p in leer_perfiles()}
    todas = sorted(leer_transacciones(), key=lambda t: t.transaction_id)

    sin_perfil = next(t for t in todas if t.customer_id not in perfiles)
    con_perfil = [t for t in todas if t.customer_id in perfiles]

    necesarias = sum(1 for s in SPECS if s.con_perfil)
    return con_perfil[:necesarias], sin_perfil, perfiles


def _construir_caso(
    idx: int, spec: Spec, txn: TransactionIn, perfil: CustomerBehaviorIn | None
) -> tuple[Case, Decision | None, list[Signal], list[AgentError], HumanResolution | None]:
    case_id = uuid4()
    # Escalonado hacia atrás: el primer caso de la lista es el más viejo.
    creado = datetime.now(UTC) - timedelta(hours=len(SPECS) - idx)

    caso = Case(
        case_id=case_id,
        transaction_id=txn.transaction_id,
        status=spec.status,
        customer_snapshot=perfil.model_dump(mode="json") if perfil else None,
        created_at=creado,
        updated_at=creado,
    )

    if spec.decision is None:
        return caso, None, [], [], None

    riesgo, confianza, base = SCORES[spec.decision]
    decidido = creado + timedelta(minutes=3)

    citas_externas = []
    if spec.con_citacion_externa:
        citas_externas.append(
            {
                "url": "https://sbs.gob.pe/alertas/fixture",
                "summary": f"{FIX} Alerta pública sobre el emisor, fuente gobernada.",
                "retrieved_at": decidido.isoformat(),
            }
        )

    if spec.degradado:
        confianza = 0.3
        rationale = (
            f"{FIX} La confianza bajó porque la verificación de inteligencia externa "
            "no completó a tiempo; el riesgo no se mueve por una falla de agente."
        )
        ruta = ROUTE_SIN_THREAT_INTEL
        threat_intel_version = None  # no se consultó snapshot — nunca "no había alertas"
    else:
        rationale = None
        ruta = FULL_ROUTE
        threat_intel_version = "fixture-intel-v1"

    decision = Decision(
        case_id=case_id,
        decision=spec.decision,
        risk_score=riesgo,
        confidence=confianza,
        base_confidence=base,
        confidence_rationale=rationale,
        scoring_version="fixture-v1",
        matched_policies=list(spec.matched),
        policy_catalog_version=CATALOG_VERSION,
        retrieval_index_version="fixture-index-v1",
        explanation_prompt_version="fixture-prompt-v1",
        threat_intel_version=threat_intel_version,
        citations_internal=[
            {"policy_id": pid, "chunk_id": f"{pid}-chunk-1", "version": DOC_VERSION}
            for pid in spec.matched
        ],
        citations_external=citas_externas,
        debate_pro_fraud=DEBATE[spec.decision][0],
        debate_pro_customer=DEBATE[spec.decision][1],
        agent_route=ruta,
        explanation_customer=EXPLANATION_CUSTOMER[spec.decision],
        explanation_audit=EXPLANATION_AUDIT[spec.decision],
        decided_at=decidido,
    )

    signals = [
        Signal(case_id=case_id, code=SIGNALS[pid][0], description=SIGNALS[pid][1], severity=SIGNALS[pid][2])
        for pid in spec.matched
    ]

    errores = (
        [
            AgentError(
                case_id=case_id,
                agent="external_threat_intel",
                error_type="TimeoutError",
                message=f"{FIX} el proveedor de búsqueda no respondió a tiempo.",
                occurred_at=decidido - timedelta(seconds=5),
            )
        ]
        if spec.degradado
        else []
    )

    resolucion = None
    if spec.resolucion is not None:
        resolucion = HumanResolution(
            case_id=case_id,
            action=spec.resolucion,
            analyst_id="analyst-fixture",
            notes=f"{FIX} resolución de ejemplo para el dashboard.",
            resolved_at=decidido + timedelta(hours=1),
        )

    return caso, decision, signals, errores, resolucion


async def sembrar() -> None:
    con_perfil, sin_perfil, perfiles = _elegir_transacciones()

    transacciones: list[TransactionIn] = []
    asignadas: list[tuple[Spec, TransactionIn]] = []
    cursor = iter(con_perfil)
    for spec in SPECS:
        txn = sin_perfil if not spec.con_perfil else next(cursor)
        asignadas.append((spec, txn))
        transacciones.append(txn)

    async with AsyncSessionLocal() as session:
        # Transacciones y, donde aplica, perfiles — upsert, mismo criterio de
        # idempotencia que `seed.py`. No requieren que `seed.py` haya corrido.
        for txn in transacciones:
            await _upsert_uno(session, Transaction, txn.model_dump(), "transaction_id")
        for pid in {t.customer_id for t in transacciones if t.customer_id in perfiles}:
            await _upsert_uno(session, CustomerBehavior, perfiles[pid].model_dump(), "customer_id")

        # Reemplazo completo de los casos de este script — "un reintento
        # sustituye, no complementa" (§7.3), aplicado a estas fixtures.
        ids = [t.transaction_id for t in transacciones]
        await session.execute(delete(Case).where(Case.transaction_id.in_(ids)))

        for idx, (spec, txn) in enumerate(asignadas):
            perfil = perfiles.get(txn.customer_id) if spec.con_perfil else None
            caso, decision, signals, errores, resolucion = _construir_caso(idx, spec, txn, perfil)
            session.add(caso)
            if decision is not None:
                session.add(decision)
                session.add_all(signals)
                session.add_all(errores)
            if resolucion is not None:
                session.add(resolucion)

        await session.commit()

    conteo_status = {s.value: 0 for s in CaseStatus}
    for spec, _ in asignadas:
        conteo_status[spec.status.value] += 1

    print(f"{len(asignadas)} casos de desarrollo sembrados:")
    for status, n in conteo_status.items():
        if n:
            print(f"  {status}: {n}")


def main() -> int:
    asyncio.run(sembrar())
    return 0


if __name__ == "__main__":
    sys.exit(main())
