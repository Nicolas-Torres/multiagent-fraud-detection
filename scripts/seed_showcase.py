"""Vitrina pública del dashboard: 5 casos reales, corridos de punta a punta
por el grafo real —no insertados a mano como `seed_dashboard_fixtures.py`—,
para que la primera visita a la URL pública muestre el sistema funcionando
de verdad, no una cola vacía.

Las 5 transacciones son filas reales de `data/transactions.csv` que además
tienen etiqueta en `data/ground_truth.csv`: la vitrina es una muestra del
mismo dataset que valida la precisión del sistema, no datos inventados para
la demo.

**Gasta llamadas reales a Anthropic y Gemini.** Idempotente por diseño: si
ya existe un caso para alguna de las 5 transacciones, lo reutiliza en vez
de volver a correr el grafo. `--reset` fuerza una corrida nueva (borra sólo
estos 5 casos, no toda la tabla).

    uv run python scripts/seed_showcase.py
    uv run python scripts/seed_showcase.py --reset

Escribe `dashboard/src/data/showcase_cases.json` con los `case_id`
resultantes — el frontend los pide por `GET /cases/{id}`, sin necesitar un
endpoint nuevo ni tocar el contrato. Cada entrada suma también `id` (slug
corto para el cooldown de "volver a ejecutar") y `payload` (la transacción
original, mismo shape que ya usa `LiveScenario` en `liveScenarios.ts`) — así
el frontend puede reejecutar cualquiera de los 5 sin pedirle el detalle al
backend primero.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from multiagent_fraud_detection.db.models import Case, CustomerBehavior, HumanResolution, Transaction
from multiagent_fraud_detection.db.session import AsyncSessionLocal
from multiagent_fraud_detection.enums import CaseStatus, DecisionType, HumanAction
from multiagent_fraud_detection.graph.builder import build_graph
from multiagent_fraud_detection.graph.context import GraphContext

from _dataset import leer_perfiles, leer_transacciones

JSON_PATH = (
    Path(__file__).resolve().parents[1] / "dashboard" / "src" / "data" / "showcase_cases.json"
)

# transaction_id -> etiqueta corta para la vitrina. El cuarto se resuelve
# como un analista lo haría, para mostrar también el flujo HITL.
CASOS = {
    "T-2579": "Aprobación limpia",
    "T-1809": "Monto y horario inusual (FP-01)",
    "T-4445": "Perfil modificado antes de operar (FP-09)",
    "T-1313": "Cuenta nueva, monto grande (FP-08)",
    "T-5816": "Escalado y resuelto por un analista",
}
RESOLVER = "T-5816"

ANALISTA_VITRINA = "vitrina-portafolio"


def _id_corto(transaction_id: str) -> str:
    """Slug sin guiones para la clave de cooldown: `_escenario_de` (en
    `api/routers/cases.py`) parte el `transaction_id` en el primer `-` tras
    `LIVE-` — un `id` con guión propio rompería ese parseo y mezclaría
    cooldowns que tienen que quedar independientes."""
    return transaction_id.lower().replace("-", "")


def _payload_de(txn) -> dict:
    """El mismo shape que `LiveScenario['payload']` en `liveScenarios.ts`:
    la transacción completa, sin `transaction_id` -eso lo genera el
    frontend fresco en cada corrida en vivo."""
    return txn.model_dump(mode="json", exclude={"transaction_id"})


async def _upsert_uno(session, modelo, valores: dict, pk: str) -> None:
    stmt = pg_insert(modelo).values(**valores)
    columnas = [k for k in valores if k != pk]
    stmt = stmt.on_conflict_do_update(
        index_elements=[pk], set_={c: getattr(stmt.excluded, c) for c in columnas}
    )
    await session.execute(stmt)


async def _resetear() -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                delete(Case).where(Case.transaction_id.in_(CASOS))
            )


async def _caso_existente(transaction_id: str) -> UUID | None:
    async with AsyncSessionLocal() as session:
        caso = await session.scalar(
            select(Case).where(Case.transaction_id == transaction_id)
        )
        return caso.case_id if caso is not None else None


async def _resolver(case_id: UUID) -> None:
    """Mismo efecto que `POST /cases/{id}/resolution` (W3), sin pasar por
    HTTP: esto es un script de siembra, no un cliente del API."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                HumanResolution(
                    case_id=case_id,
                    action=HumanAction.APPROVE,
                    analyst_id=ANALISTA_VITRINA,
                    notes=(
                        "Revisé el debate y las políticas citadas: el monto es alto "
                        "para una cuenta nueva, pero no hay otra señal de riesgo. Apruebo."
                    ),
                )
            )
            caso = await session.get(Case, case_id)
            caso.status = CaseStatus.RESOLVED


async def sembrar(reset: bool) -> list[dict]:
    if reset:
        print("--reset: borrando los 5 casos de la vitrina (no toda la tabla)")
        await _resetear()

    perfiles = {p.customer_id: p for p in leer_perfiles()}
    transacciones = {t.transaction_id: t for t in leer_transacciones() if t.transaction_id in CASOS}

    faltantes = set(CASOS) - set(transacciones)
    if faltantes:
        raise SystemExit(
            f"no se encontraron en data/transactions.csv: {sorted(faltantes)}"
        )

    async with AsyncSessionLocal() as session:
        async with session.begin():
            for tid, txn in transacciones.items():
                await _upsert_uno(session, Transaction, txn.model_dump(), "transaction_id")
                if txn.customer_id in perfiles:
                    await _upsert_uno(
                        session, CustomerBehavior,
                        perfiles[txn.customer_id].model_dump(), "customer_id",
                    )

    graph = build_graph()
    contexto = GraphContext(session_factory=AsyncSessionLocal)

    resultado: list[dict] = []
    for tid, etiqueta in CASOS.items():
        existente = await _caso_existente(tid)
        if existente is not None:
            print(f"  {tid}: ya existe ({existente}), no se vuelve a correr")
            resultado.append({
                "case_id": str(existente),
                "transaction_id": tid,
                "label": etiqueta,
                "id": _id_corto(tid),
                "payload": _payload_de(transacciones[tid]),
            })
            continue

        case_id = uuid4()
        async with AsyncSessionLocal() as session:
            async with session.begin():
                session.add(
                    Case(case_id=case_id, transaction_id=tid, status=CaseStatus.ANALYZING)
                )

        print(f"  {tid}: corriendo el grafo real...")
        await graph.ainvoke(
            {"case_id": case_id, "transaction": transacciones[tid]}, context=contexto
        )

        async with AsyncSessionLocal() as session:
            caso = await session.get(Case, case_id)
        print(f"  {tid}: {caso.status.value}")

        if tid == RESOLVER and caso.status is CaseStatus.PENDING_HUMAN:
            await _resolver(case_id)
            print(f"  {tid}: resuelto por '{ANALISTA_VITRINA}' -> RESOLVED")
        elif tid == RESOLVER:
            print(
                f"  aviso: {tid} se esperaba en PENDING_HUMAN para resolverlo y "
                f"llegó a {caso.status.value} — el Arbiter decidió distinto a lo "
                f"previsto; queda como está, no es un error del script"
            )

        resultado.append({
            "case_id": str(case_id),
            "transaction_id": tid,
            "label": etiqueta,
            "id": _id_corto(tid),
            "payload": _payload_de(transacciones[tid]),
        })

    return resultado


def _escribir(casos: list[dict]) -> None:
    salida = json.dumps(casos, indent=2, ensure_ascii=False, sort_keys=False)
    if JSON_PATH.exists() and JSON_PATH.read_text(encoding="utf-8").rstrip("\n") == salida:
        print(f"sin cambios: {JSON_PATH.name}")
        return
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(salida + "\n", encoding="utf-8")
    print(f"escrito: {JSON_PATH.name} ({len(casos)} casos)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reset", action="store_true",
        help="borra los 5 casos de la vitrina y los vuelve a correr (gasta LLM real)",
    )
    args = parser.parse_args()

    casos = asyncio.run(sembrar(args.reset))
    _escribir(casos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
