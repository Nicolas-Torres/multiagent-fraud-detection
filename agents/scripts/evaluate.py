"""Harness de evaluación contra el ground truth (entregable 7).

    uv run python scripts/evaluate.py --sample-size 60 --seed 42
    uv run python scripts/evaluate.py --mode llm --sample-size 10

Estratifica por política y por decisión, corre el grafo sobre cada transacción
muestreada y compara la decisión emitida contra `ground_truth.csv`. Reporta
precisión, recall y F1 por política y por decisión.

Reproducibilidad: mismo `--seed` → misma muestra y mismo resultado en los
agentes determinísticos. Threat Intel corre offline; el RAG y los LLM solo si
`--mode llm` (con `GraphContext` completo).

Cómo se compara:
- **Por decisión**: `decision` del grafo vs `expected_decision` del ground
  truth.
- **Por política**: las señales emitidas (vía `SIGNAL_TO_POLICY`) vs
  `expected_policies`. Así se mide la detección, no solo el veredicto final.
"""

import argparse
import asyncio
import random
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pandas as pd
from sqlalchemy import delete

from src.db.models import Case
from src.db.session import AsyncSessionLocal
from src.domain.policies import SIGNAL_TO_POLICY
from src.enums import CaseStatus, DecisionType
from src.graph.builder import build_graph
from src.graph.context import GraphContext
from src.llm.mlflow_tracking import mlflow_run
from src.llm.providers import build_embeddings, build_llm
from src.schemas.transaction import TransactionIn

DATA_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "data"

DECISIONES = [d.value for d in DecisionType]
POLITICAS = list(SIGNAL_TO_POLICY.values())


# --- Muestreo estratificado --------------------------------------------------


def muestrear(gt: pd.DataFrame, tx: pd.DataFrame, sample_size: int, seed: int) -> pd.DataFrame:
    """Estratifica por política y por decisión.

    Asegura que cada política con positivos esté representada (piso de
    positivos) y balancea las decisiones menos frecuentes. `seed` fija la
    muestra para reproducibilidad (8.5).
    """
    rng = random.Random(seed)

    positivos_por_politica: dict[str, pd.DataFrame] = {}
    for politica in POLITICAS:
        positivos = gt[gt.expected_policies.str.contains(politica, regex=False)]
        if len(positivos):
            positivos_por_politica[politica] = positivos

    # Piso por política: tantos positivos como permita la muestra por política.
    piso_por_politica = max(1, sample_size // 12)
    seleccionados: set[str] = set()
    for politica, dfp in positivos_por_politica.items():
        toma = list(dfp.transaction_id)
        rng.shuffle(toma)
        seleccionados.update(toma[:piso_por_politica])

    # Balance por decisión: asegura que CHALLENGE/BLOCK/ESCALATE aparezcan.
    for decision in ("BLOCK", "ESCALATE_TO_HUMAN", "CHALLENGE"):
        candidatos = gt[gt.expected_decision == decision]
        toma = list(candidatos.transaction_id)
        rng.shuffle(toma)
        seleccionados.update(toma[: piso_por_politica // 2])

    # Relleno aleatorio hasta `sample_size`.
    resto = list(gt.transaction_id)
    rng.shuffle(resto)
    for tid in resto:
        if len(seleccionados) >= sample_size:
            break
        seleccionados.add(tid)

    muestra = gt[gt.transaction_id.isin(seleccionados)]
    return muestra


# --- Corrida del grafo por transacción ---------------------------------------


@dataclass
class ResultadoCaso:
    transaction_id: str
    esperado: DecisionType
    emitido: DecisionType
    politicas_esperadas: set[str] = field(default_factory=set)
    politicas_detectadas: set[str] = field(default_factory=set)
    politicas_recuperadas: set[str] = field(default_factory=set)
    degradado: bool = False


async def _limpiar(session, case_id: UUID) -> None:
    # Solo se borra el caso: la transacción pertenece al dataset sembrado
    # (historial) y no se toca. El CASCADE arrastra decision, señales y errores.
    await session.execute(delete(Case).where(Case.case_id == case_id))


async def evaluar_una(
    tx_id: str,
    fila_tx: pd.Series,
    esperado: DecisionType,
    politicas_esperadas: set[str],
    graph,
    contexto: GraphContext,
) -> ResultadoCaso:
    """Crea el caso, corre el grafo, compara y limpia."""
    case_id = uuid4()
    tx_in = TransactionIn(
        transaction_id=tx_id,
        customer_id=fila_tx["customer_id"],
        amount=Decimal(str(fila_tx["amount"])),
        currency=fila_tx["currency"],
        country=fila_tx["country"],
        channel=fila_tx["chanel"],
        device_id=fila_tx["device_id"],
        timestamp=pd.Timestamp(fila_tx["timestamp"], tz="UTC").to_pydatetime(),
        merchant_id=fila_tx["merchant_id"],
    )

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Idempotencia: si una corrida anterior dejó un caso para esta
            # transacción (por ejemplo, un proceso cortado), se reemplaza.
            # La transacción en sí pertenece al dataset y no se toca.
            await session.execute(
                delete(Case).where(Case.transaction_id == tx_in.transaction_id)
            )
            session.add(Case(case_id=case_id, transaction_id=tx_in.transaction_id, status=CaseStatus.ANALYZING))

        try:
            estado = await graph.ainvoke(
                {"case_id": case_id, "transaction": tx_in},
                context=contexto,
            )
            emitido = estado.get("decision", DecisionType.ESCALATE_TO_HUMAN)
            detectadas = {
                SIGNAL_TO_POLICY[s.code]
                for s in estado.get("signals", [])
                if s.code in SIGNAL_TO_POLICY
            }
            # Retrieval: políticas que el RAG recuperó como respaldo (9.3).
            recuperadas = {c.policy_id for c in estado.get("citations_internal", [])}
            degradado = bool(estado.get("agent_errors"))
        finally:
            async with session.begin():
                await _limpiar(session, case_id)

    return ResultadoCaso(
        transaction_id=tx_in.transaction_id,
        esperado=esperado,
        emitido=emitido,
        politicas_esperadas=politicas_esperadas,
        politicas_detectadas=detectadas,
        politicas_recuperadas=recuperadas,
        degradado=degradado,
    )


# --- Métricas ----------------------------------------------------------------


def _f1(p: float, r: float) -> float:
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def _prec_recall(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return precision, recall, _f1(precision, recall)


def reportar(resultados: list[ResultadoCaso]) -> dict:
    """Métricas por decisión y por política + resumen."""
    print("\n== Métricas por decisión ==")
    por_decision: dict[DecisionType, dict] = {}
    for r in resultados:
        d = por_decision.setdefault(r.esperado, {"tp": 0, "fp": 0, "fn": 0})
        if r.emitido == r.esperado:
            d["tp"] += 1
        else:
            d["fp"] += 1
    for decision in DECISIONES:
        d = por_decision.get(DecisionType(decision), {"tp": 0, "fp": 0, "fn": 0})
        p, rec, f1 = _prec_recall(d["tp"], d["fp"], d["fn"])
        print(f"  {decision:18} prec={p:.3f} rec={rec:.3f} f1={f1:.3f} (n={d['tp']+d['fp']})")

    print("\n== Métricas por política ==")
    por_politica: dict[str, dict] = {}
    for r in resultados:
        for politica in POLITICAS:
            d = por_politica.setdefault(politica, {"tp": 0, "fp": 0, "fn": 0})
            en_esperado = politica in r.politicas_esperadas
            en_detectadas = politica in r.politicas_detectadas
            if en_esperado and en_detectadas:
                d["tp"] += 1
            elif en_esperado and not en_detectadas:
                d["fn"] += 1
            elif not en_esperado and en_detectadas:
                d["fp"] += 1
    for politica in POLITICAS:
        d = por_politica[politica]
        p, rec, f1 = _prec_recall(d["tp"], d["fp"], d["fn"])
        print(f"  {politica} prec={p:.3f} rec={rec:.3f} f1={f1:.3f} (n={d['tp']+d['fn']})")

    print("\n== Métricas del retrieval (recall@k) ==")
    # recall@k: de las políticas esperadas con señal, ¿cuántas recuperó el RAG
    # como cita? Solo sobre casos con políticas esperadas (n > 0).
    hits_retrieval = 0
    total_retrieval = 0
    for r in resultados:
        relevantes = r.politicas_esperadas & r.politicas_detectadas
        if not relevantes:
            continue
        total_retrieval += len(relevantes)
        hits_retrieval += len(relevantes & r.politicas_recuperadas)
    recall_retrieval = hits_retrieval / total_retrieval if total_retrieval else 0.0
    print(f"  recall@{len(resultados)}={recall_retrieval:.3f} "
          f"({hits_retrieval}/{total_retrieval} políticas relevantes recuperadas)")

    degradados = sum(1 for r in resultados if r.degradado)
    return {
        "n": len(resultados),
        "degradados": degradados,
        "recall_retrieval": recall_retrieval,
        "por_decision": por_decision,
        "por_politica": por_politica,
    }


# --- Modo comparación --------------------------------------------------------


async def correr_modo(
    gt: pd.DataFrame,
    tx: pd.DataFrame,
    muestra: pd.DataFrame,
    modo: str,
    seed: int,
) -> list[ResultadoCaso]:
    """Corre el grafo sobre la muestra en el modo indicado."""
    if modo == "llm":
        contexto = GraphContext(
            session_factory=AsyncSessionLocal,
            llm=build_llm(),
            embeddings=build_embeddings(),
            threat_intel_offline=True,
        )
    else:
        # determinístico: RAG con embeddings (determinista) + Arbiter por
        # precedencia (sin LLM). Mide la calidad de la detección + respaldo.
        contexto = GraphContext(
            session_factory=AsyncSessionLocal,
            embeddings=build_embeddings(),
            threat_intel_offline=True,
        )

    graph = build_graph()
    filas_tx = tx.set_index("transaction_id")
    resultados: list[ResultadoCaso] = []

    for i, fila in enumerate(muestra.itertuples(index=False), 1):
        tid = fila.transaction_id
        politicas = {p for p in fila.expected_policies.split(";") if p}
        r = await evaluar_una(
            tid,
            filas_tx.loc[tid],
            DecisionType(fila.expected_decision),
            politicas,
            graph,
            contexto,
        )
        resultados.append(r)
        if i % 10 == 0 or i == len(muestra):
            print(f"  {i}/{len(muestra)} evaluados")

    return resultados


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-size", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mode", choices=["deterministic", "llm", "comparison"], default="deterministic")
    parser.add_argument("--out", type=str, default="", help="ruta donde guardar el reporte")
    args = parser.parse_args()

    gt = pd.read_csv(DATA_DIR / "ground_truth.csv", dtype=str, keep_default_na=False)
    tx = pd.read_csv(DATA_DIR / "transactions.csv", dtype=str, keep_default_na=False)

    muestra = muestrear(gt, tx, args.sample_size, args.seed)
    lineas = [f"Muestra: {len(muestra)} transacciones (seed={args.seed})",
              f"  decisiones: {dict(muestra.expected_decision.value_counts())}"]
    for txt in lineas:
        print(txt)

    def registrar(txt: str) -> None:
        print(txt)
        lineas.append(txt)

    if args.mode == "comparison":
        registrar("\n--- Modo determinístico ---")
        det = await correr_modo(gt, tx, muestra, "deterministic", args.seed)
        registrar("\n--- Modo LLM ---")
        llm = await correr_modo(gt, tx, muestra, "llm", args.seed)
        registrar("\n== RESUMEN determinístico vs LLM ==")
        for nombre, res in (("determinístico", det), ("LLM", llm)):
            registrar(f"  {nombre}: {sum(1 for r in res if r.emitido == r.esperado)}/{len(res)} "
                      f"aciertos · {sum(1 for r in res if r.degradado)} degradados")
    else:
        resultados = await correr_modo(gt, tx, muestra, args.mode, args.seed)
        import io
        buf = io.StringIO()
        _stdout = sys.stdout
        sys.stdout = buf
        try:
            resumen = reportar(resultados)
        finally:
            sys.stdout = _stdout
        for linea in buf.getvalue().splitlines():
            registrar(linea)
        aciertos = sum(1 for r in resultados if r.emitido == r.esperado)
        registrar(f"\nAciertos: {aciertos}/{len(resultados)} ({aciertos/len(resultados):.1%})")

        # Registro en MLflow (9.2, 9.3): parámetros + métricas de la corrida.
        with mlflow_run(
            f"{args.mode}_{args.seed}",
            params={
                "modo": args.mode,
                "sample_size": args.sample_size,
                "seed": args.seed,
                "version_catalogo": "2025.1",
                "scoring_version": "2026.1",
                "llm_provider": "deterministic" if args.mode != "llm" else "llm",
            },
        ) as run:
            if run is not None:
                for decision in DECISIONES:
                    d = resumen["por_decision"].get(DecisionType(decision), {"tp": 0, "fp": 0, "fn": 0})
                    p, rec, f1 = _prec_recall(d["tp"], d["fp"], d["fn"])
                    run.log_metric(f"precision_{decision.lower()}", p)
                    run.log_metric(f"recall_{decision.lower()}", rec)
                    run.log_metric(f"f1_{decision.lower()}", f1)
                for politica in POLITICAS:
                    d = resumen["por_politica"][politica]
                    p, rec, f1 = _prec_recall(d["tp"], d["fp"], d["fn"])
                    run.log_metric(f"precision_{politica}", p)
                    run.log_metric(f"recall_{politica}", rec)
                    run.log_metric(f"f1_{politica}", f1)
                run.log_metric("recall_retrieval", resumen["recall_retrieval"])
                run.log_metric("accuracy", aciertos / len(resultados))
                run.log_metric("degradados", resumen["degradados"])

    if args.out:
        from pathlib import Path
        Path(args.out).write_text("\n".join(lineas) + "\n", encoding="utf-8")
        registrar(f"\nReporte guardado en {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
