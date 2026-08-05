"""Partir un documento normativo en fragmentos indexables.

Hoy **un chunk por documento**: once políticas de una línea no se benefician de
partirse, y partir por partir mete ruido en el ranking. Pero la estrategia entra
por parámetro, no está horneada, porque el corpus real —circulares y manuales— sí
va a necesitar partirse y ese día tiene que ser una llamada distinta, no una
reescritura.

**La estrategia no es una perilla de runtime.** ADR-0012 §3 la lista entre los
parámetros que suben `index_version`: cambiar el `Splitter` produce vectores
nuevos, así que cambia con una generación nueva del índice, no en caliente.

## Por qué `chunk_id` se ve así

`{policy_id}:{source_version}:{ordinal}`. Es redundante con tres columnas de
`policy_chunks` y con dos campos de `InternalCitation`, y la redundancia se
conserva a propósito (ADR-0012 §5): el identificador **viaja al auditor**, y uno
legible se depura de un vistazo.

La contrapartida es que nunca puede contradecir a sus hermanos, y eso se resuelve
acá teniendo **un solo constructor**. `chunk_id_for` es la única forma de armarlo
y `chunk_policy` la única forma de armar un `Chunk`; un id inconsistente no es
algo que haya que detectar, es algo que no se puede escribir.

Lleva la versión del **documento** y no la del índice: es lo que hace que una
cita de enero siga resolviendo contra el índice reconstruido en marzo.

## Qué se indexa

**Todas las políticas, sin mirar su estado.** Es contraintuitivo y es el punto:
una política `PENDING` —documento sin vinculación— o `EXCLUDED` —FP-10, no
evaluable— jamás va a aparecer en `matched_policies`, así que la pierna de
autorización no puede citarla nunca. El descubrimiento es su **única** vía de
llegar a un caso. Filtrarlas acá dejaría fuera precisamente las que dependen del
índice para existir.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from multiagent_fraud_detection.domain.catalog import Policy

# Un partidor recibe el texto de la norma y devuelve sus fragmentos, en orden.
Splitter = Callable[[str], list[str]]


@dataclass(frozen=True, slots=True)
class Chunk:
    """Un fragmento listo para embeber y persistir en `policy_chunks`."""

    chunk_id: str
    policy_id: str
    source_version: str
    ordinal: int
    content: str


def chunk_id_for(policy_id: str, source_version: str, ordinal: int) -> str:
    """El único lugar donde se arma un `chunk_id`.

    Que sea único es lo que sostiene el invariante de ADR-0012 §5. Si alguna vez
    hay un segundo lugar, la redundancia deja de ser barata y pasa a ser un
    riesgo.
    """
    return f"{policy_id}:{source_version}:{ordinal}"


# --------------------------------------------------------------------------- #
# Estrategias
# --------------------------------------------------------------------------- #


def whole_document(text: str) -> list[str]:
    """La estrategia vigente: el documento entero, un solo fragmento."""
    limpio = text.strip()
    return [limpio] if limpio else []


def by_paragraph(text: str) -> list[str]:
    """Parte en párrafos separados por una línea en blanco.

    No está en uso: existe para que "el chunker está parametrizado" sea un hecho
    verificable por un test y no una promesa. Adoptarla es cambiar el argumento
    **y** subir la generación de `index_version`.
    """
    partes = re.split(r"\n\s*\n", text)
    return [p.strip() for p in partes if p.strip()]


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #


def chunk_policy(policy: Policy, *, split: Splitter = whole_document) -> tuple[Chunk, ...]:
    """Los fragmentos de una política, en orden.

    El `ordinal` es la posición dentro del documento y arranca en cero. Es parte
    del `chunk_id`, así que reordenar los fragmentos cambia identidades: otra
    razón por la que cambiar de estrategia es una generación nueva.
    """
    return tuple(
        Chunk(
            chunk_id=chunk_id_for(policy.policy_id, policy.version, i),
            policy_id=policy.policy_id,
            source_version=policy.version,
            ordinal=i,
            content=fragmento,
        )
        for i, fragmento in enumerate(split(policy.text))
    )


def chunk_all(
    policies: Iterable[Policy], *, split: Splitter = whole_document
) -> tuple[Chunk, ...]:
    """Todos los fragmentos del catálogo, ordenados por política y posición.

    Sin filtrar por estado: ver el encabezado del módulo. El orden es estable
    para que dos corridas produzcan la misma secuencia de llamadas al proveedor
    y el diff de una reindexación sea legible.
    """
    return tuple(
        chunk
        for policy in sorted(policies, key=lambda p: p.policy_id)
        for chunk in chunk_policy(policy, split=split)
    )
