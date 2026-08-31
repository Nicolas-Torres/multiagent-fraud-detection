"""Escenarios diversos para "ejecutar en vivo" en el dashboard: transacciones
reales, elegidas para que un visitante no tenga que probar 30 veces un
escenario tipo APPROVE antes de toparse con un CHALLENGE, un BLOCK o un
ESCALATE_TO_HUMAN.

**Nunca corre el grafo, nunca gasta un LLM.** La elección se apoya en
`data/ground_truth.csv` -el motor de reglas determinístico que generó esas
etiquetas, sin ningún proveedor de por medio (`scripts/check_policies.py`:
"Sin red, sin LLM. Las 7000 transacciones en segundos")-, así que cuesta
cero llamadas a un proveedor. El veredicto real lo sigue decidiendo el
grafo, recién cuando alguien de verdad ejecuta el escenario.

**El texto visible nunca nombra el veredicto esperado.** `expected_decision`
es una etiqueta determinística; el Arbiter con LLM tiene la última palabra y
ocasionalmente puede diferir de ella (ADR-0016: escala el piso, no lo
cruza, pero sí puede escalar). Prometer un veredicto en la etiqueta y que
el sistema real diga otro se leería como un bug, no como el margen que el
propio diseño le da al árbitro. La descripción visible sólo nombra la
señal (`expected_policies`), igual que los tres escenarios ya escritos a
mano en `liveScenarios.ts`.

    uv run python scripts/seed_diverse_scenarios.py

Escribe `dashboard/src/data/diverse_scenarios.json`, mismo shape
`LiveScenario[]` que ya usa `liveScenarios.ts` -id, label, description,
payload-, listo para importar tal cual.
"""

import json
import sys
from datetime import timedelta
from pathlib import Path

from _dataset import leer_ground_truth, leer_transacciones

JSON_PATH = (
    Path(__file__).resolve().parents[1] / "dashboard" / "src" / "data" / "diverse_scenarios.json"
)

# Ya en uso por la vitrina (`seed_showcase.py`) o por los tres escenarios
# hardcodeados de `liveScenarios.ts` -no elegir un candidato de estos
# clientes evita que una corrida en vivo choque con una fila ya sembrada
# (la lección de FP-02/FP-05 de la etapa anterior: colisionar con una fila
# real ya existente dispara señales que no tienen que ver con el escenario).
CLIENTES_EN_USO = {"CU-0643", "CU-0543", "CU-0364", "CU-0054", "CU-0587", "CU-0426"}

VENTANA_COLISION = timedelta(hours=3)

# expected_decision -> cuántos candidatos elegir. Nada de APPROVE extra: ya
# hay de sobra con la vitrina y el escenario "approve" de `liveScenarios.ts`.
CUPOS = {"CHALLENGE": 2, "BLOCK": 2, "ESCALATE_TO_HUMAN": 2}

# Política -> frase corta para la descripción visible. Mismo estilo que las
# tres descripciones ya escritas a mano en `liveScenarios.ts`: describe la
# señal, nunca el veredicto.
POLITICA_A_FRASE = {
    "FP-01": "monto y horario fuera de lo habitual",
    "FP-02": "canal nuevo con monto alto",
    "FP-03": "velocity: mismo dispositivo, varias transacciones seguidas",
    "FP-04": "card testing: cobros chicos seguidos de uno grande",
    "FP-05": "geolocalización imposible entre dos transacciones",
    "FP-06": "canal nuevo con monto que duplica el promedio",
    "FP-07": "comercio con historial de fraude",
    "FP-08": "cuenta nueva con un monto grande",
    "FP-09": "cambio de datos justo antes de operar",
    "FP-10": "alerta pública activa sobre el emisor",
    "FP-11": "suma diaria fuera de lo habitual",
}


def _id_corto(transaction_id: str) -> str:
    """Ver la misma nota en `seed_showcase.py`: sin guiones, o rompe el
    parseo del cooldown en `api/routers/cases.py`."""
    return transaction_id.lower().replace("-", "")


def _texto(politicas: list[str]) -> tuple[str, str]:
    frases = [POLITICA_A_FRASE.get(p, p) for p in politicas]
    label = frases[0][0].upper() + frases[0][1:]
    plural = len(frases) > 1
    cuerpo = "; ".join(frases)
    codigos = ", ".join(politicas)
    palabra = "Señales reales" if plural else "Señal real"
    return label, f"{palabra} del dataset: {cuerpo} ({codigos})."


def _hay_colision(txn, todas: list) -> bool:
    """Otra fila real del mismo cliente dentro de la ventana -evitada acá en
    la selección, no a mano: un visitante que dispara este escenario en
    vivo no debería chocar contra una transacción que el dataset ya trae
    sembrada cerca en el tiempo."""
    return any(
        otra.transaction_id != txn.transaction_id
        and otra.customer_id == txn.customer_id
        and abs(otra.timestamp - txn.timestamp) <= VENTANA_COLISION
        for otra in todas
    )


def elegir() -> list[dict]:
    transacciones = leer_transacciones()
    ground_truth = leer_ground_truth()
    por_id = {t.transaction_id: t for t in transacciones}

    elegidos: list[dict] = []
    for decision, cupo in CUPOS.items():
        candidatos = sorted(
            tid
            for tid, gt in ground_truth.items()
            if gt["decision"] == decision
            and gt["policies"]
            and tid in por_id
            and por_id[tid].customer_id not in CLIENTES_EN_USO
        )

        encontrados = 0
        for tid in candidatos:
            if encontrados >= cupo:
                break
            txn = por_id[tid]
            if _hay_colision(txn, transacciones):
                continue
            label, description = _texto(ground_truth[tid]["policies"])
            elegidos.append({
                "id": _id_corto(tid),
                "label": label,
                "description": description,
                "payload": txn.model_dump(mode="json", exclude={"transaction_id"}),
            })
            encontrados += 1

        if encontrados < cupo:
            print(
                f"aviso: sólo se encontraron {encontrados}/{cupo} candidatos "
                f"sin colisión para {decision}"
            )

    return elegidos


def _escribir(escenarios: list[dict]) -> None:
    salida = json.dumps(escenarios, indent=2, ensure_ascii=False, sort_keys=False)
    if JSON_PATH.exists() and JSON_PATH.read_text(encoding="utf-8").rstrip("\n") == salida:
        print(f"sin cambios: {JSON_PATH.name}")
        return
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(salida + "\n", encoding="utf-8")
    print(f"escrito: {JSON_PATH.name} ({len(escenarios)} escenarios)")


def main() -> int:
    escenarios = elegir()
    _escribir(escenarios)
    return 0


if __name__ == "__main__":
    sys.exit(main())
