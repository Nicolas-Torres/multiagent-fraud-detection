"""Cómo se arma una cita interna. ADR-0011.

Dos bloques, y lo que se persiste es su unión:

| bloque | Cómo | Aporta | Garantía |
|---|---|---|---|
| **Autorización** | lookup por `policy_id` de `matched_policies` | toda política que disparó | **total** |
| **Descubrimiento** | búsqueda vectorial desde los códigos de señal | políticas relacionadas que **no** dispararon | ninguna |

Acá vive la primera y la unión. La segunda es una consulta al índice y vive en
`db/repositories/policy_chunks.py`.

## La autorización no consulta el índice

Se resuelve contra el **catálogo** —que da la versión vigente de cada política— y
el constructor de `chunk_id`. Tres consecuencias, y las tres son el punto:

1. **Recall 1.0 por construcción.** No hay recuperación aproximada de por medio,
   así que no puede faltar una política que disparó.
2. **Sobrevive a que el índice no exista.** Un documento publicado y no indexado
   sigue siendo citable por identidad e invisible por similitud — el estado que
   ADR-0012 declara legítimo y que la tercera métrica del entregable 6 mide. Si
   esta bloque consultara `policy_chunks`, ese estado dejaría de ser legítimo y
   pasaría a escalar el caso.
3. **Sobrevive a que el proveedor de embeddings se caiga.** No hay llamada de red
   en este camino.

## Por qué esto existe

Si `citations_internal` saliera sólo de la búsqueda vectorial, el motor podría
disparar FP-03 y el índice devolver FP-05 y FP-02: el caso se decide `BLOCK`
correctamente y **cita normas que no aplicó**. No hay excepción, el invariante de
lista no vacía se cumple, y el auditor recibe una explicación coherente y falsa.
Ninguna huella lo detecta: los dos artefactos están intactos, lo que falló fue el
emparejamiento.
"""

from __future__ import annotations

from collections.abc import Iterable

from multiagent_fraud_detection.domain.catalog import PolicyCatalog
from multiagent_fraud_detection.retrieval.chunking import chunk_id_for
from multiagent_fraud_detection.schemas.decision import InternalCitation

#: Qué fragmento del documento cita la autorización.
#:
#: Con un chunk por documento, el cero es el documento entero. El día que el
#: chunker parta por párrafo esto queda corto —habría que citar el fragmento que
#: corresponde, o todos— y ese día se decide con el caso a la vista. Se declara
#: acá para que la limitación sea visible en vez de estar escondida en un literal.
AUTHORIZING_ORDINAL = 0


def authorization_citations(
    catalog: PolicyCatalog, policy_ids: Iterable[str]
) -> list[InternalCitation]:
    """Una cita por cada política que disparó, ordenadas por `policy_id`.

    El orden es alfabético y no de emisión: dos corridas con las mismas
    políticas tienen que producir el mismo JSON, o el diff del harness es ruido.
    """
    citas = []

    for policy_id in sorted(set(policy_ids)):
        politica = catalog[policy_id]
        citas.append(
            InternalCitation(
                policy_id=policy_id,
                chunk_id=chunk_id_for(
                    policy_id, politica.version, AUTHORIZING_ORDINAL
                ),
                version=politica.version,
            )
        )

    return citas


def merge_citations(
    authorized: Iterable[InternalCitation], discovered: Iterable[InternalCitation]
) -> list[InternalCitation]:
    """La unión de las dos bloques, sin repetir, autorización primero.

    Se deduplica por `chunk_id`, que identifica el fragmento dentro de una
    versión del documento. Una política puede llegar por las dos vías —disparó y
    además el índice la recuperó— y eso no es dos citas.

    **La autorización va primero y no se puede perder.** El orden no es estético:
    quien lea la traza de auditoría ve antes lo que respaldó el veredicto y
    después lo que el sistema encontró alrededor.

    No se agrega `retrieved_by` para distinguirlas. El Arbiter las separa
    intersecando `matched_policies` con `citations_internal`, y el contrato ya
    expone las dos cosas por separado: no se modela lo que se puede derivar.
    """
    unidas: dict[str, InternalCitation] = {}

    for cita in (*authorized, *discovered):
        unidas.setdefault(cita.chunk_id, cita)

    return list(unidas.values())


def missing_authorization(
    citations: Iterable[InternalCitation], policy_ids: Iterable[str]
) -> tuple[str, ...]:
    """Políticas que dispararon y no están citadas. Vacío = invariante cumplido.

    Es la forma verificable de:

        citations_internal ⊇ { documento(p) : p ∈ matched_policies }

    Devuelve las que faltan en vez de un booleano porque los dos consumidores
    necesitan el detalle: el nodo para afirmarlo, y el Arbiter para explicar por
    qué degrada a `ESCALATE_TO_HUMAN` en vez de emitir un veredicto sin respaldo.
    """
    citadas = {c.policy_id for c in citations}
    return tuple(sorted(set(policy_ids) - citadas))
