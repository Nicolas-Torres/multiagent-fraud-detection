"""Golden set del Arbiter: evaluación de calidad con DeepEval.

    uv run --group eval python scripts/eval_golden_set.py [--dry-run]

`deepeval` vive en un grupo de dependencias aparte (`eval`, opt-in): no forma
parte de `uv sync` por defecto, para no inflar el entorno de cada `dev` con su
cadena de dependencias por un script que ningún gate corre. `--dry-run` no
necesita el grupo instalado -no importa `deepeval`-, así que sirve también
para verificar el golden set con el entorno por defecto.

Deuda declarada por ADR-0013 ("de la etapa de agentes con LLM, no de esta") y
pagada acá: el gate que corre sobre las 7 000 filas (`check_policies.py`,
`test_ground_truth.py`) sigue midiendo `domain/engine.py` sin tocar; esto mide
el Arbiter LLM, aparte y sin bloquear.

**No es un gate.** Reporta, no bloquea — ningún puntaje de esta corrida falla
`pytest` ni CI. Toca red dos veces por caso (el Arbiter real y el juez de
DeepEval) y requiere `scripts/seed.py` corrido: los siete casos son
transacciones reales del dataset de 7 000 (`data/eval/golden_set_llm_agents.json`),
no fixtures sintéticos — curados a mano, no muestreados; ver el comentario de
ese archivo y `docs/plan_llm_agents.md` paso 6.

`--dry-run` imprime los casos sin invocar al grafo ni a DeepEval: sirve para
verificar el cableado sin gastar una corrida real.

## Las dos métricas

No se mide "¿el veredicto respeta el piso?" — eso ya lo garantiza la cuarta
guarda de W2 estructuralmente, y medir con un LLM lo que el código ya prueba
sería peor que no medirlo: dos fuentes de verdad para el mismo hecho.

Lo que un gate de código no puede ver es la *calidad* del razonamiento:

- **`fundamentacion_del_debate`**: ¿el argumento de cada lado se queda dentro
  de la evidencia del caso, o inventa?
- **`calidad_del_juicio_del_arbiter`**: cuando el Arbiter se aparta del piso,
  ¿el `rationale` señala qué evidencia adicional lo justifica, o es cautela
  genérica sin razonamiento nuevo? Sólo se mide en los casos donde hubo
  desvío — un veredicto que coincide con el piso no tiene rationale que juzgar.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_DNS, UUID, uuid5

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import delete, select

from _dataset import leer_transacciones

from multiagent_fraud_detection.db.models import Case, Decision, ThreatIndicator
from multiagent_fraud_detection.db.session import AsyncSessionLocal
from multiagent_fraud_detection.enums import CaseStatus, IndicatorType
from multiagent_fraud_detection.graph.builder import build_graph
from multiagent_fraud_detection.graph.context import GraphContext
from multiagent_fraud_detection.intel.snapshot import SNAPSHOT_VERSION

GOLDEN_SET = (
    Path(__file__).resolve().parents[1] / "data" / "eval" / "golden_set_llm_agents.json"
)

JUEZ_MODEL = "claude-sonnet-5"


def case_id_for(transaction_id: str) -> UUID:
    """Determinista, no aleatorio: dos corridas ocupan el mismo `case_id` y
    `persist_decision` reemplaza el agregado en vez de acumular filas."""
    return uuid5(NAMESPACE_DNS, f"eval-golden-set:{transaction_id}")


def cargar_casos() -> list[dict]:
    return json.loads(GOLDEN_SET.read_text(encoding="utf-8"))["cases"]


async def limpiar(transaction_ids: list[str]) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                delete(Case).where(
                    Case.case_id.in_([case_id_for(t) for t in transaction_ids])
                )
            )
            await session.execute(
                delete(ThreatIndicator).where(
                    ThreatIndicator.source_url == "https://sbs.gob.pe/alertas/eval-golden-set"
                )
            )


async def sembrar_indicador(issuer_bank: str, antes_de: datetime) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                ThreatIndicator(
                    indicator_type=IndicatorType.ISSUER,
                    value=issuer_bank,
                    observed_at=antes_de - timedelta(hours=3),
                    retrieved_at=datetime.now(UTC),
                    source_url="https://sbs.gob.pe/alertas/eval-golden-set",
                    summary="Alerta simulada del golden set (no es una alerta real)",
                    snapshot_version=SNAPSHOT_VERSION,
                    added_by="eval_golden_set",
                )
            )


def construir_metricas():
    from deepeval.metrics import GEval
    from deepeval.models import DeepEvalBaseLLM
    from deepeval.test_case import SingleTurnParams

    class ClaudeEvalModel(DeepEvalBaseLLM):
        """Juez de DeepEval sobre el mismo proveedor que el sistema evalúa,
        para no introducir una segunda cuenta o clave sólo para medir
        calidad.

        Definida acá adentro -no a nivel de módulo- porque hereda de
        `DeepEvalBaseLLM`: `deepeval.metrics.utils.initialize_model` hace un
        `isinstance` real, así que subclasear es obligatorio y no alcanza con
        implementar el protocolo por duck typing. Mantenerla local es lo que
        deja a `--dry-run` sin importar `deepeval`.
        """

        def __init__(self, model: str = JUEZ_MODEL):
            self.model = model

        def load_model(self):
            from anthropic import Anthropic

            return Anthropic()

        def generate(self, prompt: str) -> str:
            cliente = self.load_model()
            respuesta = cliente.messages.create(
                model=self.model,
                # DeepEval le pide al juez razonamiento paso a paso más un
                # JSON con score y motivo; con `context` largo (dos
                # argumentos de debate completos) 1024 truncaba la respuesta
                # a mitad del JSON y `trimAndLoadJson` fallaba.
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in respuesta.content if b.type == "text")

        async def a_generate(self, prompt: str) -> str:
            # El cliente de Anthropic es sincrono; correrlo directo
            # bloquearia el loop de deepeval igual que bloquearia el del
            # grafo (ver nodes.py).
            return await asyncio.to_thread(self.generate, prompt)

        def get_model_name(self) -> str:
            return self.model

    juez = ClaudeEvalModel()

    fundamentacion = GEval(
        name="fundamentacion_del_debate",
        evaluation_steps=[
            "Compara el argumento (`actual_output`) contra la evidencia real "
            "del caso (`context`): señales, políticas disparadas y puntaje "
            "de riesgo.",
            "Penaliza fuerte cualquier hecho, señal o política que el "
            "argumento mencione y no esté en `context`.",
            "No penalices que el argumento reconozca que la evidencia es "
            "débil o insuficiente: eso es honestidad, no invención.",
        ],
        evaluation_params=[
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.CONTEXT,
        ],
        threshold=0.5,
        model=juez,
    )

    calidad_del_juicio = GEval(
        name="calidad_del_juicio_del_arbiter",
        evaluation_steps=[
            "`input` describe el piso determinístico que el Arbiter superó "
            "y `context` trae la evidencia que ese piso no considera: "
            "señales aisladas, agentes degradados, los dos argumentos de "
            "debate.",
            "El `actual_output` es el `rationale` del Arbiter para haberse "
            "apartado del piso. Tiene que señalar explícitamente cuál de "
            "esa evidencia adicional lo justifica.",
            "Penaliza un rationale que repita el piso o apele a cautela "
            "genérica sin señalar evidencia concreta de `context`.",
        ],
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.CONTEXT,
        ],
        threshold=0.5,
        model=juez,
    )

    return fundamentacion, calidad_del_juicio


async def correr_caso(graph, contexto, caso: dict, transacciones: dict) -> dict | None:
    transaction_id = caso["transaction_id"]
    tx = transacciones.get(transaction_id)
    if tx is None:
        print(f"  ! {transaction_id}: no está en data/transactions.csv, se salta")
        return None

    if caso.get("seed_threat_indicator") and tx.issuer_bank:
        await sembrar_indicador(tx.issuer_bank, tx.timestamp)
        contexto.indicators.invalidate()

    cid = case_id_for(transaction_id)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(delete(Case).where(Case.case_id == cid))
            session.add(
                Case(case_id=cid, transaction_id=transaction_id, status=CaseStatus.ANALYZING)
            )

    await graph.ainvoke({"case_id": cid, "transaction": tx}, context=contexto)

    async with AsyncSessionLocal() as session:
        decision = await session.scalar(select(Decision).where(Decision.case_id == cid))

    if decision is None:
        print(f"  ! {transaction_id}: no dejó fila en `decisions`")
        return None

    return {
        "transaction_id": transaction_id,
        "decision": decision.decision.value,
        "confidence_rationale": decision.confidence_rationale,
        "signals_context": [
            f"{s.code} ({s.severity.value}): {s.description}" for s in decision.signals
        ],
        "degraded_agents": decision.degraded_agents,
        "pro_fraud_argument": decision.debate_pro_fraud,
        "pro_customer_argument": decision.debate_pro_customer,
    }


async def evaluar(dry_run: bool) -> int:
    casos = cargar_casos()
    transaction_ids = [c["transaction_id"] for c in casos]

    print(f"Golden set: {len(casos)} casos ({GOLDEN_SET.name})")
    for c in casos:
        print(f"  - {c['transaction_id']}: {c['reason']}")

    if dry_run:
        print("\n--dry-run: no se invoca al grafo ni a DeepEval.")
        return 0

    transacciones = {t.transaction_id: t for t in leer_transacciones()}
    fundamentacion, calidad_del_juicio = construir_metricas()

    graph = build_graph()
    contexto = GraphContext(session_factory=AsyncSessionLocal)

    resultados = []
    try:
        for caso in casos:
            print(f"\n=== {caso['transaction_id']} ===")
            resultado = await correr_caso(graph, contexto, caso, transacciones)
            if resultado is None:
                continue

            from deepeval.test_case import LLMTestCase

            for rol, campo in (
                ("pro-fraude", "pro_fraud_argument"),
                ("pro-cliente", "pro_customer_argument"),
            ):
                caso_debate = LLMTestCase(
                    input=f"Argumento {rol} sobre {caso['transaction_id']}",
                    actual_output=resultado[campo],
                    context=resultado["signals_context"] or ["(sin señales)"],
                )
                try:
                    score = fundamentacion.measure(caso_debate)
                    print(f"  fundamentacion_del_debate [{rol}]: {score:.2f}")
                except Exception as exc:  # noqa: BLE001 - un juez que falla no tumba la corrida
                    print(f"  fundamentacion_del_debate [{rol}]: error del juez ({exc})")

            if resultado["confidence_rationale"]:
                caso_juicio = LLMTestCase(
                    input=f"Veredicto final: {resultado['decision']}",
                    actual_output=resultado["confidence_rationale"],
                    context=(
                        resultado["signals_context"]
                        + [f"agentes degradados: {resultado['degraded_agents']}"]
                        + [f"argumento pro-fraude: {resultado['pro_fraud_argument']}"]
                        + [f"argumento pro-cliente: {resultado['pro_customer_argument']}"]
                    ),
                )
                try:
                    score = calidad_del_juicio.measure(caso_juicio)
                    print(f"  calidad_del_juicio_del_arbiter: {score:.2f}")
                except Exception as exc:  # noqa: BLE001 - idem
                    print(f"  calidad_del_juicio_del_arbiter: error del juez ({exc})")
            else:
                print("  calidad_del_juicio_del_arbiter: n/a (sin desvío del piso)")

            resultados.append(resultado)
    finally:
        await limpiar(transaction_ids)

    print(f"\n{len(resultados)}/{len(casos)} casos evaluados. Reporta, no bloquea.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(evaluar(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
