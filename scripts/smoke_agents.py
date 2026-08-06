"""Los agentes determinísticos contra Postgres, comparados con el ground truth.

    uv run python scripts/smoke_agents.py            → muestra estratificada
    uv run python scripts/smoke_agents.py --todas    → las 7 000 (lento)
    uv run python scripts/smoke_agents.py --por-politica 10

Requiere `docker compose up -d` y `seed.py --reset`.

## Por qué existe, si `check_policies.py` ya da 0 discrepancias

Porque prueban cosas distintas. El gate arma el historial **en memoria**,
acumulando transacción por transacción en orden cronológico: ahí el invariante
*as-of* se cumple por construcción, no hay forma de violarlo.

Acá el historial sale de Postgres, donde **el futuro también está en la tabla**
—el seed carga las 7 000 de una vez—. Si una consulta olvidara el `as_of`, o si
la ventana estuviera mal, o si la transacción bajo análisis se contara dos veces
en su propia ventana, el gate seguiría en verde y esto lo vería.

Y el modo de falla es traicionero: **funciona bien en producción**, donde el
futuro todavía no existe cuando llega el caso. Solo miente en evaluación, y
miente hacia arriba —más recall del real—. Un sistema certificado con ese sesgo
no funciona el día que se despliega.

## Qué NO cubre

El grafo completo. Se invocan los tres agentes de la etapa directamente, sin
pasar por LangGraph: los demás nodos siguen siendo stubs y el invariante mandaría
todo a `ESCALATE_TO_HUMAN` sin RAG, tapando lo que interesa medir acá.
"""

import argparse
import asyncio
import random
import sys
from collections import defaultdict

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from langgraph.runtime import Runtime
from sqlalchemy.ext.asyncio import async_sessionmaker

from multiagent_fraud_detection.db.session import engine
from multiagent_fraud_detection.graph.context import GraphContext
from multiagent_fraud_detection.graph.nodes import (
    behavioral_pattern,
    evidence_aggregation,
    transaction_context,
)

from _dataset import leer_ground_truth, leer_transacciones

SIN_PERFIL = "__sin_perfil__"
LIMPIAS = "__limpias__"


def muestrear(transacciones, esperado, *, por_politica: int, semilla: int = 0):
    """Muestra estratificada: cada política, más los bordes.

    Un muestreo uniforme sobre 7 000 traería casi puros `APPROVE` —el 91% del
    dataset— y dejaría políticas enteras sin ejercitar. Los estratos son las diez
    políticas más dos bordes que no son políticas: cliente sin perfil, y casos
    completamente limpios que verifican que el sistema no inventa señales.
    """
    por_estrato = defaultdict(list)
    for t in transacciones:
        etiquetas = esperado[t.transaction_id]["policies"]
        if etiquetas:
            for p in etiquetas:
                por_estrato[p].append(t)
        else:
            por_estrato[LIMPIAS].append(t)

    rng = random.Random(semilla)
    elegidas: dict[str, object] = {}
    for estrato, candidatas in sorted(por_estrato.items()):
        cuantas = por_politica if estrato != LIMPIAS else por_politica * 2
        for t in rng.sample(candidatas, min(cuantas, len(candidatas))):
            elegidas[t.transaction_id] = t

    return list(elegidas.values()), dict(por_estrato)


async def evaluar(transaccion, runtime) -> dict:
    """Los tres agentes de la etapa, en el mismo orden que el grafo."""
    ola1 = await asyncio.gather(
        transaction_context({"transaction": transaccion}, runtime),
        behavioral_pattern({"transaction": transaccion}, runtime),
    )

    # Lo que hacen los reducers del estado cuando LangGraph une el superstep.
    acumulado: dict = {"signals": [], "matched_policies": [], "agent_errors": []}
    for salida in ola1:
        for clave in acumulado:
            acumulado[clave] += salida.get(clave, [])

    return await evidence_aggregation(acumulado, runtime)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--todas", action="store_true", help="las 7 000 (lento)")
    ap.add_argument("--por-politica", type=int, default=5)
    args = ap.parse_args()

    transacciones = leer_transacciones()
    esperado = leer_ground_truth()

    if args.todas:
        muestra, estratos = transacciones, {}
    else:
        muestra, estratos = muestrear(
            transacciones, esperado, por_politica=args.por_politica
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    runtime = Runtime(context=GraphContext(session_factory=session_factory))

    print(f"evaluando {len(muestra)} transacciones contra Postgres...")
    if estratos:
        resumen = ", ".join(
            f"{k}:{min(args.por_politica, len(v))}" for k, v in sorted(estratos.items())
        )
        # `->` y no `→`: la consola de Windows es cp1252 y U+2192 no existe
        # ahi, asi que el `print` levanta UnicodeEncodeError y tumba el smoke
        # entero justo al final. Es el unico caracter del repo con ese problema.
        print(f"  estratos -> {resumen}")

    fallos = []
    sin_perfil = 0
    ejemplo = None

    for t in muestra:
        salida = await evaluar(t, runtime)
        obtenidas = salida.get("policies", [])
        esperadas = esperado[t.transaction_id]["policies"]

        if any(s.code == "NO_CUSTOMER_PROFILE" for s in salida.get("evidence", [])):
            sin_perfil += 1
        if ejemplo is None and len(obtenidas) >= 1:
            ejemplo = (t, salida)

        if obtenidas != esperadas:
            fallos.append((t.transaction_id, esperadas, obtenidas, salida))

    await engine.dispose()

    print(f"\ncoinciden con el ground truth : {len(muestra) - len(fallos)}")
    print(f"divergen                      : {len(fallos)}")
    print(f"clientes sin perfil en la muestra: {sin_perfil}")

    if fallos:
        print("\nDIVERGENCIAS — el historial de Postgres no dice lo mismo que el offline:")
        for tid, esp, got, salida in fallos[:15]:
            print(f"  {tid}: esperado={esp} obtenido={got}")
            for s in salida.get("evidence", []):
                print(f"      [{s.severity.value}] {s.code}")
        print(
            "\nSospechosos habituales: `as_of` reemplazado por `now()`, ventana "
            "distinta de la del gate, o la transacción bajo análisis contándose "
            "en su propia ventana."
        )
        return 1

    if ejemplo is not None:
        t, salida = ejemplo
        print(f"\nejemplo · {t.transaction_id} · {t.amount} {t.currency}")
        print(f"  politicas       : {salida['policies']}")
        print(f"  risk_score      : {salida['risk_score']}")
        print(f"  base_confidence : {salida['base_confidence']}")
        print(f"  scoring_version : {salida['scoring_version']}")
        for s_ in salida["evidence"]:
            print(f"    [{s_.severity.value:6s}] {s_.code:26s} {s_.description[:70]}")

    print("\nOK — Postgres y el motor offline coinciden")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
