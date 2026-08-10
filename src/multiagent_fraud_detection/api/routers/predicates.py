"""`GET /api/v1/predicates`: la biblioteca de predicados, para el compositor
del dashboard (§2.3, §3.3 del contrato) — la vinculación de una política es
`action` + estos predicados compuestos, nunca código nuevo.

Sin `Depends`: `LIBRARY` es un diccionario a nivel de módulo, poblado al
importar `domain.predicates`, igual de estático que el catálogo pero sin
siquiera el paso de releer un archivo.
"""

from __future__ import annotations

from fastapi import APIRouter

from multiagent_fraud_detection.domain.predicates import LIBRARY, Predicate
from multiagent_fraud_detection.schemas.predicate import ParamSpecRead, PredicateSpec

router = APIRouter(tags=["predicates"])


def _proyectar(predicado: Predicate) -> PredicateSpec:
    return PredicateSpec(
        name=predicado.name,
        # Orden estable: `requires` es un frozenset, y su iteración no lo es.
        requires=sorted(predicado.requires),
        severity=predicado.severity,
        params={
            nombre: ParamSpecRead.model_validate(spec)
            for nombre, spec in predicado.params.items()
        },
        description=predicado.description,
    )


@router.get("/predicates", response_model=list[PredicateSpec])
async def listar_predicados() -> list[PredicateSpec]:
    return [_proyectar(p) for p in sorted(LIBRARY.values(), key=lambda p: p.name)]
