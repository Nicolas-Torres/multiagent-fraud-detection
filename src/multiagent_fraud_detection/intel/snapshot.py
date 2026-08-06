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

MODEL = "claude-sonnet-4-6"
TEMPLATE_TAG = "issuer-alert"
GENERATION = 1

SNAPSHOT_VERSION = f"{MODEL}:{TEMPLATE_TAG}:v{GENERATION}"
