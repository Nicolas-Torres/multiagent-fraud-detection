"""El intérprete determinístico.

Recorre las políticas que le tocan a un agente, evalúa sus predicados sobre el
contexto y devuelve dos cosas separadas: las **señales** —observaciones ciertas—
y las **políticas que matchearon** —la conjunción completa—.

## Por qué son dos salidas y no una

Una transacción de 4 500 con promedio 1 200, a las 14:00. `amount_over_avg_multiple(3)`
se cumple; `outside_usual_hours()` no. FP-01 **no** matchea —y está bien—, pero el
monto sí está fuera de rango, y esa observación es cierta.

Si el intérprete cortara en el primer predicado que falla, esa señal se perdería.
Y es justamente la clase de señal que más importa: las que no vienen acompañadas
de una política que las explique son las que el Arbiter tiene que ponderar y las
que el monitoreo del entregable 6 vigila para detectar drift.

Por eso: **se evalúan todos los predicados, siempre.** `matched` es una conclusión
sobre los resultados, no una condición de corte.

## Determinismo

Dos corridas idénticas producen las mismas señales en el mismo orden. No es
prolijidad: el harness compara listas, y sin orden estable el diff es ruido. El
orden sale de recorrer las políticas por `policy_id` y sus predicados en el orden
en que la vinculación los escribió.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from multiagent_fraud_detection.domain.catalog import Owner, Policy, PolicyCatalog
from multiagent_fraud_detection.domain.params import PRECEDENCE
from multiagent_fraud_detection.domain.predicates import EvalContext
from multiagent_fraud_detection.enums import DecisionType, Severity


@dataclass(frozen=True, slots=True)
class EmittedSignal:
    """Una observación cierta, lista para persistirse en `signals`."""

    code: str
    description: str
    severity: Severity
    observed: dict[str, Any] = field(default_factory=dict)
    from_policies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Evaluation:
    signals: tuple[EmittedSignal, ...] = ()
    matched_policies: tuple[str, ...] = ()
    skipped_policies: tuple[str, ...] = ()

    def merge(self, other: Evaluation) -> Evaluation:
        """Une el resultado de dos agentes. Lo usa Evidence Aggregation.

        Las señales se deduplican otra vez porque los dos agentes podrían emitir
        el mismo código —hoy no ocurre, pero depende del catálogo, y el catálogo
        es dato mutable—.
        """
        return _consolidate(
            list(self.signals) + list(other.signals),
            tuple(sorted(set(self.matched_policies) | set(other.matched_policies))),
            tuple(sorted(set(self.skipped_policies) | set(other.skipped_policies))),
        )


def _consolidate(
    crudas: list[EmittedSignal],
    matched: tuple[str, ...],
    skipped: tuple[str, ...],
) -> Evaluation:
    """Deduplica por código, preservando el orden de primera aparición.

    Un mismo código puede venir de varias políticas: `AMOUNT_OVER_USUAL_AVG` sale
    de FP-01 (3×), FP-04 (2×) y FP-06 (2×). Se conserva la **primera** aparición
    en el orden determinístico y se acumulan las políticas que la produjeron.

    El costo: si dos instancias del mismo predicado difieren en parámetros, la
    descripción que sobrevive es la de la primera política por `policy_id`. Es
    aceptable porque las tres afirman lo mismo con distinto umbral —superar 3×
    implica superar 2×— y `from_policies` conserva la trazabilidad completa.
    """
    por_codigo: dict[str, EmittedSignal] = {}
    for s in crudas:
        previa = por_codigo.get(s.code)
        if previa is None:
            por_codigo[s.code] = s
        else:
            por_codigo[s.code] = EmittedSignal(
                code=previa.code,
                description=previa.description,
                severity=previa.severity,
                observed=previa.observed,
                from_policies=tuple(
                    dict.fromkeys(previa.from_policies + s.from_policies)
                ),
            )
    return Evaluation(tuple(por_codigo.values()), matched, skipped)


def evaluate_policy(policy: Policy, ctx: EvalContext) -> tuple[list[EmittedSignal], bool]:
    """Evalúa una política. Devuelve sus señales y si la conjunción se cumplió.

    No corta: los predicados que se cumplen emiten señal aunque otro falle.
    """
    señales: list[EmittedSignal] = []
    condicionales: list[EmittedSignal] = []
    cumplidos = 0

    for paso in policy.condition:
        hit = paso.predicate.fn(ctx, **paso.params)
        if hit is None:
            continue
        cumplidos += 1
        emitida = EmittedSignal(
            code=paso.predicate.signal_code(**paso.params),
            description=hit.detail,
            severity=paso.predicate.severity,
            observed=hit.observed,
            from_policies=(policy.policy_id,),
        )
        (señales if paso.predicate.standalone else condicionales).append(emitida)

    matched = cumplidos == len(policy.condition)
    if matched:
        señales.extend(condicionales)
    return señales, matched


def evaluate(catalog: PolicyCatalog, owner: Owner, ctx: EvalContext) -> Evaluation:
    """Corre las políticas de un agente sobre un caso.

    Una política cuyos insumos no están disponibles —el caso típico es un cliente
    sin perfil— **no se evalúa y no falla**: se registra en `skipped_policies`.
    Eso es lo que reproduce el comportamiento del etiquetador sin un `if` por
    política, y lo que hace que Transaction Context siga produciendo evidencia
    cuando el cliente no existe.
    """
    disponibles = ctx.available
    crudas: list[EmittedSignal] = []
    matched: list[str] = []
    skipped: list[str] = []

    for policy in catalog.evaluable_by(owner):
        if not policy.requires <= disponibles:
            skipped.append(policy.policy_id)
            continue
        señales, ok = evaluate_policy(policy, ctx)
        crudas.extend(señales)
        if ok:
            matched.append(policy.policy_id)

    return _consolidate(crudas, tuple(matched), tuple(skipped))


def prescribed_action(
    catalog: PolicyCatalog, matched_policies: tuple[str, ...]
) -> DecisionType:
    """La acción que el catálogo manda, resolviendo conflictos por precedencia.

    **No es la decisión del sistema.** El veredicto lo emite el Arbiter, que puede
    apartarse de esto con justificación auditable (ADR-0006). Esta función existe
    por dos motivos: es la línea base determinística contra la que el harness
    compara el enfoque agéntico completo (entregable 7), y es el mismo cálculo con
    el que se construyó `expected_decision` en el ground truth —si el Arbiter
    usara otra precedencia, la comparación sería injusta—.
    """
    acciones = {
        catalog[pid].action.value
        for pid in matched_policies
        if catalog[pid].action is not None
    }
    return DecisionType(next((a for a in PRECEDENCE if a in acciones), "APPROVE"))
