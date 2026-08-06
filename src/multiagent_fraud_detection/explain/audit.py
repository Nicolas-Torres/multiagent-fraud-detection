"""`explanation_audit`: el hecho, no la redacción.

Se arma con una plantilla y **nunca** con un LLM. La razón no es económica.

`explanation_audit` es el registro de por qué el sistema decidió lo que decidió:
qué política, en qué versión, qué señales, qué agentes corrieron, con qué índice
se recuperó. Todo eso ya está en el estado como dato estructurado. Pasarlo por un
modelo generativo no agrega información —solo puede perderla o alterarla— y
rompe la propiedad que el harness necesita: dos corridas de la misma transacción
tienen que producir el mismo texto, o el diff del entregable 7 es ruido.

Es la misma distinción que el proyecto ya hizo dos veces. `Decimal` para el
dinero y `float` para el score; tabla para lo que el sistema **mide** y JSONB
para lo que **archiva**. Acá: plantilla para lo que se **audita**, LLM para lo
que se **lee**.

## Consecuencia práctica

Este texto nunca degrada. Si el proveedor de LLM está caído, `explanation_customer`
cae a plantilla pero `explanation_audit` sale idéntico a como saldría un día
normal — y menciona la degradación, que es justo lo que un auditor querría ver.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from multiagent_fraud_detection.enums import DecisionType

SIN_POLITICAS = "ninguna política del catálogo se cumplió por completo"


def _lista(items: Sequence[str], vacio: str = "ninguno") -> str:
    return ", ".join(items) if items else vacio


def build_audit_explanation(state: dict[str, Any]) -> str:
    """El párrafo de auditoría, determinístico y completo.

    Recibe el estado y no el `Decision` persistido: corre **antes** de persistir,
    y lo que hay que explicar es lo que se decidió, no lo que quedó guardado.
    """
    decision: DecisionType = state["decision"]
    politicas = list(state.get("policies", []))
    citas = state.get("citations_internal", [])
    señales = state.get("signals", [])
    ruta = state.get("agent_route", [])
    degradados = sorted({e.agent for e in state.get("agent_errors", [])})

    # Las citas que respaldan el veredicto y las que solo lo acompañan. La
    # distinción no se guarda en ningún lado: se deriva intersecando, que es la
    # razón por la que `merge_citations` no agrega un campo `retrieved_by`.
    respaldo = [c for c in citas if c.policy_id in set(politicas)]
    contexto = [c for c in citas if c.policy_id not in set(politicas)]

    lineas = [
        f"Decisión: {decision.value}.",
    ]

    if politicas:
        detalle = ", ".join(
            f"{c.policy_id} (v{c.version}, {c.chunk_id})" for c in respaldo
        )
        lineas.append(
            f"Políticas aplicadas: {detalle}. La acción surge de la precedencia "
            f"entre las acciones que prescriben."
        )
    else:
        lineas.append(
            f"{SIN_POLITICAS.capitalize()}; no hay norma que citar y la decisión "
            f"no se apoya en ninguna."
        )

    if señales:
        lineas.append(
            "Señales detectadas: "
            + ", ".join(f"{s.code} ({s.severity.value})" for s in señales)
            + "."
        )
    else:
        lineas.append("No se detectaron señales.")

    if contexto:
        lineas.append(
            "Políticas relacionadas recuperadas por similitud, que no se "
            "cumplieron y no respaldan la decisión: "
            + _lista([c.policy_id for c in contexto])
            + "."
        )

    citas_externas = state.get("citations_external", [])
    if citas_externas:
        detalle = "; ".join(
            f"{c.summary} ({c.url}, recuperada {c.retrieved_at.isoformat()})"
            for c in citas_externas
        )
        lineas.append(f"Evidencia externa: {detalle}.")

    riesgo = state.get("risk_score")
    base = state.get("base_confidence")
    confianza = state.get("confidence")
    lineas.append(
        f"Riesgo determinístico {riesgo}; confianza base {base}; "
        f"confianza final {confianza}"
        + (
            f", ajustada: {state['confidence_rationale']}."
            if state.get("confidence_rationale")
            else "."
        )
    )

    if degradados:
        lineas.append(
            f"Evidencia incompleta: {_lista(degradados)} no pudo completar su "
            f"análisis; la confianza refleja esa degradación."
        )

    lineas.append(f"Ruta de agentes: {' → '.join(ruta) if ruta else 'ninguna'}.")

    sellos = [
        ("catálogo", state.get("policy_catalog_version")),
        ("scoring", state.get("scoring_version")),
        ("índice", state.get("retrieval_index_version")),
        ("prompt", state.get("explanation_prompt_version")),
        ("snapshot", state.get("threat_intel_version")),
    ]
    lineas.append(
        "Versiones: "
        + ", ".join(f"{nombre} {valor or 'n/a'}" for nombre, valor in sellos)
        + "."
    )

    return " ".join(lineas)
