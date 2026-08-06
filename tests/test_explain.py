"""Qué se le dice al cliente y qué no. Sin red, sin base.

El grueso de estos tests no verifica que el texto sea bueno —eso es LLM-as-judge
y va en otro carril— sino que **no filtre la regla**. Es control de divulgación,
y por eso se prueba con la misma dureza que un invariante.
"""

import re

from multiagent_fraud_detection.enums import DecisionType, Severity
from multiagent_fraud_detection.explain.audit import build_audit_explanation
from multiagent_fraud_detection.explain.customer import (
    PROMPT_VERSION,
    SAFE_THEMES,
    SYSTEM_PROMPT,
    build_prompt,
    fallback_explanation,
    safe_themes,
)
from multiagent_fraud_detection.explain.narrator import FakeNarrator
from multiagent_fraud_detection.graph.state import AgentError, WorkingSignal
from multiagent_fraud_detection.schemas.decision import ExternalCitation, InternalCitation

from conftest import utc

TODOS = list(SAFE_THEMES)


def señal(code, severity=Severity.MEDIUM, emitted_by="behavioral_pattern"):
    """`emitted_by` es obligatorio en la señal en vuelo.

    No se persiste —`Signal` no expone procedencia— pero lo consumen Evidence
    Aggregation, para fusionar redundantes, y el harness, para atribuir falsos
    positivos. Acá da lo mismo cuál sea: la explicación no lo mira.
    """
    return WorkingSignal(
        code=code,
        description=f"detalle de {code}",
        severity=severity,
        emitted_by=emitted_by,
    )


def estado(**extra):
    base = {
        "decision": DecisionType.BLOCK,
        "policies": ["FP-03"],
        "citations_internal": [
            InternalCitation(
                policy_id="FP-03", chunk_id="FP-03:2025.1:0", version="2025.1"
            )
        ],
        "signals": [señal("DEVICE_VELOCITY")],
        "agent_route": ["transaction_context", "internal_policy_rag"],
        "risk_score": 0.5,
        "base_confidence": 0.4,
        "confidence": 0.4,
        "policy_catalog_version": "2025.1-b1",
        "scoring_version": "1.0",
        "retrieval_index_version": "gemini-embedding-2:1536:doc:1",
    }
    return {**base, **extra}


# --------------------------------------------------------------------------- #
# Control de divulgación
# --------------------------------------------------------------------------- #


def test_ningun_tema_seguro_menciona_un_numero():
    """Un umbral, una ventana o un conteo en el texto al cliente es la regla."""
    for codigo, tema in SAFE_THEMES.items():
        assert not re.search(r"\d", tema), f"{codigo} filtra un número: {tema!r}"


def test_ningun_tema_seguro_menciona_un_policy_id():
    for codigo, tema in SAFE_THEMES.items():
        assert not re.search(r"FP-\d", tema, re.I), f"{codigo} nombra una política"


def test_el_prompt_solo_ve_temas_traducidos():
    """El modelo nunca recibe códigos: recibe frases ya sanitizadas."""
    prompt = build_prompt(DecisionType.BLOCK, safe_themes(TODOS))

    for codigo in TODOS:
        assert codigo not in prompt, f"{codigo} llegó crudo al prompt"
    assert "FP-" not in prompt


def test_el_comercio_en_lista_negra_no_se_delata():
    """Afirmar que un comercio tiene historial de fraude es hablar de un tercero."""
    tema = SAFE_THEMES["MERCHANT_BLACKLISTED"].lower()
    for palabra in ("fraude", "lista", "negra", "historial", "bloquead"):
        assert palabra not in tema


def test_la_senal_sin_valor_para_el_titular_se_omite():
    """`NO_CUSTOMER_PROFILE` describe la evidencia, no la transacción."""
    assert safe_themes(["NO_CUSTOMER_PROFILE"]) == []


def test_un_codigo_desconocido_falla_cerrado():
    """Lo peor que puede pasar es un motivo vago, no un umbral."""
    temas = safe_themes(["CODIGO_QUE_NO_EXISTE"])
    assert temas
    assert not re.search(r"\d", temas[0])


def test_los_temas_se_agrupan():
    """Tres formas de "monto inusual" son un solo motivo para quien lo lee.

    Agrupar reduce lo que el mensaje revela sobre qué regla exacta disparó.
    """
    temas = safe_themes(
        ["AMOUNT_OVER_USUAL_AVG", "AMOUNT_OVER_SEGMENT_AVG", "AMOUNT_OVER_ABSOLUTE"]
    )
    assert len(temas) < 3


def test_el_system_prompt_prohibe_inventar():
    minuscula = SYSTEM_PROMPT.lower()
    for regla in ("nunca", "únicamente", "no inventes"):
        assert regla in minuscula


def test_hay_respaldo_para_los_cuatro_veredictos():
    """El contrato tipa el campo como `str`: la ausencia no es representable."""
    for decision in DecisionType:
        texto = fallback_explanation(decision)
        assert texto and not re.search(r"\d", texto)


# --------------------------------------------------------------------------- #
# La explicación de auditoría
# --------------------------------------------------------------------------- #


def test_la_auditoria_si_nombra_la_politica_y_su_version():
    """Lo que el cliente no puede ver, el analista sí."""
    texto = build_audit_explanation(estado())
    assert "FP-03" in texto
    assert "2025.1" in texto
    assert "DEVICE_VELOCITY" in texto
    assert "BLOCK" in texto


def test_la_auditoria_separa_respaldo_de_contexto():
    """Las citas de descubrimiento no respaldan: el párrafo lo dice."""
    texto = build_audit_explanation(
        estado(
            citations_internal=[
                InternalCitation(
                    policy_id="FP-03", chunk_id="FP-03:2025.1:0", version="2025.1"
                ),
                InternalCitation(
                    policy_id="FP-09", chunk_id="FP-09:2025.1:0", version="2025.1"
                ),
            ]
        )
    )
    assert "no se cumplieron" in texto
    assert "FP-09" in texto


def test_la_auditoria_es_reproducible():
    """Dos corridas, el mismo texto. Es la propiedad que el LLM rompería."""
    assert build_audit_explanation(estado()) == build_audit_explanation(estado())


def test_la_auditoria_declara_la_degradacion():
    texto = build_audit_explanation(
        estado(
            agent_errors=[
                AgentError(
                    agent="internal_policy_rag",
                    error_type="ConnectionError",
                    message="caído",
                )
            ]
        )
    )
    assert "Evidencia incompleta" in texto
    assert "internal_policy_rag" in texto


def test_la_auditoria_dice_cuando_no_hubo_politicas():
    texto = build_audit_explanation(
        estado(decision=DecisionType.APPROVE, policies=[], citations_internal=[])
    )
    assert "ninguna política" in texto.lower()


def test_la_auditoria_lista_los_cinco_sellos():
    texto = build_audit_explanation(
        estado(
            explanation_prompt_version=PROMPT_VERSION,
            threat_intel_version="claude-sonnet-4-6:issuer-alert:v1",
        )
    )
    for sello in ("catálogo", "scoring", "índice", "prompt", "snapshot"):
        assert sello in texto
    assert "claude-sonnet-4-6:issuer-alert:v1" in texto


def test_la_auditoria_distingue_no_consultado_de_snapshot_vacio():
    """`null` es *no se consultó snapshot* —el nodo degradó antes de
    completar el lookup—, nunca *no había alertas*. La distinción tiene que
    verse en el texto, no perderse en un `state.get(..., "n/a")` silencioso."""
    texto = build_audit_explanation(estado(threat_intel_version=None))
    assert "snapshot n/a" in texto


def test_la_auditoria_nombra_la_fuente_y_el_indicador_de_una_alerta_externa():
    """ADR-0015: qué indicador, de qué fuente. El titular nunca ve esto —es
    `explain/customer.py` el que lo esconde—, pero el analista sí."""
    texto = build_audit_explanation(
        estado(
            policies=["FP-03", "FP-10"],
            citations_internal=[
                InternalCitation(
                    policy_id="FP-03", chunk_id="FP-03:2025.1:0", version="2025.1"
                ),
                InternalCitation(
                    policy_id="FP-10", chunk_id="FP-10:2025.1:0", version="2025.1"
                ),
            ],
            citations_external=[
                ExternalCitation(
                    url="https://sbs.gob.pe/alertas/x",
                    summary="SBS - Alerta de fraude sobre el emisor",
                    retrieved_at=utc(2026, 3, 10, 12, 0),
                )
            ],
            threat_intel_version="claude-sonnet-4-6:issuer-alert:v1",
        )
    )
    assert "Evidencia externa" in texto
    assert "SBS - Alerta de fraude sobre el emisor" in texto
    assert "https://sbs.gob.pe/alertas/x" in texto


def test_la_auditoria_sin_evidencia_externa_no_menciona_el_parrafo():
    assert "Evidencia externa" not in build_audit_explanation(estado())


def test_el_narrador_falso_no_se_disfraza_de_real():
    assert FakeNarrator().narrate("s", "u") == "[explicación de prueba]"
