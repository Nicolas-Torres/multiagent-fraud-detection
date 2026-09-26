"""Versión del corpus de inteligencia externa.

Tres segmentos, igual que `PROMPT_VERSION` y `INDEX_VERSION`: el modelo que
ejecutó la búsqueda, la plantilla de query y la generación. Se sella en
`decisions.threat_intel_version`.

**Ninguno de los tres es variable de entorno.** Uno configurable por `env` podría
cambiarse sin que suba la versión, y entonces dos corridas con el mismo sello
habrían consultado corpus distintos — que es exactamente lo que el sello existe
para impedir.

Subir `GENERATION` obliga a re-ejecutar el fetch completo: las filas de la
generación anterior dejan de ser visibles para el lookup. Es el costo aceptado en
ADR-0014 a cambio de que el sello no pueda mentir.
"""

# Haiku y no Sonnet (ADR-0026): el modelo sólo formula la búsqueda; las fuentes
# salen de los bloques de la herramienta. ID con fecha: fijo, no se mueve por
# debajo del sello.
MODEL = "claude-haiku-4-5-20251001"
TEMPLATE_TAG = "issuer-alert"
# 2: se agregó `SYSTEM_PROMPT` y cambió el modelo (ADR-0026).
GENERATION = 2

SNAPSHOT_VERSION = f"{MODEL}:{TEMPLATE_TAG}:v{GENERATION}"

# La plantilla, pegada a `TEMPLATE_TAG`: editar el texto sin subir `GENERATION`
# dejaría un `SNAPSHOT_VERSION` sellado que ya no describe qué se preguntó.
#
# Sin ventana de días en el texto: el fetch es una foto periódica que no sabe
# de antemano qué ventana se va a evaluar en runtime. La de FP-10 —24h— se
# resuelve *as-of* contra `transaction.timestamp` en el momento del lookup, no
# en el momento de la búsqueda; restringir la query la sesgaría sin ganancia.
QUERY_TEMPLATE = (
    "Alertas públicas de fraude, phishing o compromiso de seguridad "
    "sobre el banco emisor {issuer_bank} en Perú."
)


# Parámetro de derivación, igual que la plantilla: puede cambiar la consulta que
# el modelo le pasa a la herramienta. Pide que no redacte nada: el texto se
# descarta (`searcher._extraer`) y se paga igual (incidente 0010).
SYSTEM_PROMPT = (
    "Tu única tarea es ejecutar la herramienta de búsqueda web con la consulta "
    "del usuario. Haz exactamente una búsqueda, sin escribir nada antes. Después "
    "de recibir los resultados, responde solamente: LISTO"
)


def build_query(issuer_bank: str) -> str:
    """La query para un emisor. Determinista: mismo emisor, misma query."""
    return QUERY_TEMPLATE.format(issuer_bank=issuer_bank)


# Versión aparte para `fetch_threat_intel.py --fake`, mismo criterio que
# `FAKE_INDEX_VERSION`: un snapshot de prueba no puede confundirse con el
# corpus real, y el lookup en runtime filtra por `SNAPSHOT_VERSION` exacto.
FAKE_SNAPSHOT_VERSION = f"fake:{TEMPLATE_TAG}:v{GENERATION}"
