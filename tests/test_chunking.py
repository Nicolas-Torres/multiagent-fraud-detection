"""El chunker y las plantillas: sin red, sin base.

Lo que se prueba acá es lo que ADR-0012 declara invariante y parámetro de
derivación. El resto del paso 2 —que reindexar no duplique— necesita Postgres y
vive en `scripts/index_policies.py --fake`.
"""

import pytest

from multiagent_fraud_detection.domain.catalog import Policy, PolicyState
from multiagent_fraud_detection.retrieval.chunking import (
    by_paragraph,
    chunk_all,
    chunk_id_for,
    chunk_policy,
    whole_document,
)
from multiagent_fraud_detection.retrieval.embeddings import (
    DIMENSIONS,
    FAKE_INDEX_VERSION,
    INDEX_VERSION,
    MODEL,
    FakeEmbedder,
    format_document,
    format_query,
)


def politica(pid="FP-01", version="2025.1", text="Monto mayor al habitual -> CHALLENGE",
             state=PolicyState.ACTIVE) -> Policy:
    return Policy(policy_id=pid, version=version, text=text, state=state)


# --------------------------------------------------------------------------- #
# El invariante de `chunk_id`
# --------------------------------------------------------------------------- #


def test_chunk_id_no_puede_contradecir_a_sus_hermanos():
    """La redundancia de ADR-0012 §5, verificada donde se produce."""
    for chunk in chunk_policy(politica()):
        assert chunk.chunk_id == chunk_id_for(
            chunk.policy_id, chunk.source_version, chunk.ordinal
        )


def test_chunk_id_es_estable_entre_corridas():
    """Dos corridas sobre la misma política producen los mismos identificadores.

    Es lo que hace que una cita persistida siga resolviendo después de
    re-embeber: el `chunk_id` no depende del modelo ni del momento.
    """
    primera = [c.chunk_id for c in chunk_policy(politica())]
    segunda = [c.chunk_id for c in chunk_policy(politica())]
    assert primera == segunda == ["FP-01:2025.1:0"]


def test_chunk_id_lleva_la_version_del_documento_no_la_del_indice():
    chunk, = chunk_policy(politica(version="2025.2"))
    assert chunk.chunk_id == "FP-01:2025.2:0"
    assert INDEX_VERSION not in chunk.chunk_id


# --------------------------------------------------------------------------- #
# Las estrategias
# --------------------------------------------------------------------------- #


def test_por_defecto_un_chunk_por_documento():
    chunks = chunk_policy(politica(text="Primer párrafo.\n\nSegundo párrafo."))
    assert len(chunks) == 1
    assert chunks[0].ordinal == 0
    assert "Segundo párrafo." in chunks[0].content


def test_la_estrategia_es_de_verdad_un_parametro():
    """`by_paragraph` no está en uso; existe para que esto sea verificable."""
    chunks = chunk_policy(
        politica(text="Primero.\n\nSegundo.\n\nTercero."), split=by_paragraph
    )
    assert [c.ordinal for c in chunks] == [0, 1, 2]
    assert [c.chunk_id for c in chunks] == [
        "FP-01:2025.1:0",
        "FP-01:2025.1:1",
        "FP-01:2025.1:2",
    ]
    assert [c.content for c in chunks] == ["Primero.", "Segundo.", "Tercero."]


def test_documento_vacio_no_produce_chunks():
    assert chunk_policy(politica(text="   \n  ")) == ()
    assert whole_document("") == []


# --------------------------------------------------------------------------- #
# Qué entra al índice
# --------------------------------------------------------------------------- #


def test_se_indexan_tambien_las_politicas_no_evaluables():
    """Son las que **sólo** pueden llegar a un caso por descubrimiento.

    Una `PENDING` o una `EXCLUDED` nunca aparece en `matched_policies`, así que
    el bloque de autorización no puede citarla. Filtrarlas del índice las dejaría
    incitables por las dos vías.
    """
    catalogo = [
        politica("FP-01", state=PolicyState.ACTIVE),
        politica("FP-10", state=PolicyState.EXCLUDED),
        politica("FP-11", state=PolicyState.PENDING),
        politica("FP-12", state=PolicyState.STALE),
    ]
    indexadas = {c.policy_id for c in chunk_all(catalogo)}
    assert indexadas == {"FP-01", "FP-10", "FP-11", "FP-12"}


def test_chunk_all_ordena_por_politica():
    catalogo = [politica("FP-03"), politica("FP-01"), politica("FP-02")]
    assert [c.policy_id for c in chunk_all(catalogo)] == ["FP-01", "FP-02", "FP-03"]


# --------------------------------------------------------------------------- #
# Las plantillas y la versión
# --------------------------------------------------------------------------- #


def test_las_plantillas_son_asimetricas():
    """Documento y consulta se formatean distinto: es un modelo de recuperación."""
    assert format_document("texto") == "title: none | text: texto"
    assert format_query("texto") == "task: search result | query: texto"
    assert format_document("x") != format_query("x")


def test_index_version_se_compone_de_los_parametros():
    """No se escribe a mano: cambiar el modelo la mueve sola."""
    assert INDEX_VERSION.startswith(f"{MODEL}:{DIMENSIONS}:")
    assert INDEX_VERSION.split(":") == [MODEL, str(DIMENSIONS), "doc", "1"]


def test_el_indice_falso_no_puede_confundirse_con_el_real():
    """Lo que impide que un vector de prueba se cuele no es la disciplina."""
    assert FAKE_INDEX_VERSION != INDEX_VERSION
    assert not FAKE_INDEX_VERSION.startswith(MODEL)


# --------------------------------------------------------------------------- #
# El embedder falso
# --------------------------------------------------------------------------- #


def test_el_embedder_falso_es_determinista_y_normalizado():
    fake = FakeEmbedder()
    a, b = fake.embed("misma entrada"), fake.embed("misma entrada")

    assert a == b
    assert len(a) == DIMENSIONS
    assert sum(v * v for v in a) == pytest.approx(1.0)
    assert fake.embed("otra entrada") != a
