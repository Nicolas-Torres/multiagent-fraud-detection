"""El proveedor de búsqueda, detrás de un puerto. Tercer proveedor del sistema.

| Puerto | Proveedor | Rol | Sello |
|---|---|---|---|
| `Embedder` | Gemini | recuperación | `retrieval_index_version` |
| `Narrator` | Anthropic | generación | `explanation_prompt_version` |
| `Searcher` | Anthropic | inteligencia externa | `threat_intel_version` |

**Lo consume el script de build, no el grafo** (ADR-0014). Se inyecta igual que
los otros para que un test pueda pasar un doble sin red ni clave.

## La regla que gobierna este adaptador

**La URL sale del bloque de resultado; el modelo no la escribe.** Los bloques
`web_search_result` los produce la herramienta del proveedor con lo que
efectivamente recuperó; la prosa del modelo es texto generado y puede fabricar un
enlace que parece plausible. Es ADR-0011 aplicado a la otra frontera: identidad
para lo que autoriza, generación sólo para lo que se lee.

Por la misma razón el `summary` que se persiste es el **título de la fuente**, no
un resumen redactado. Nada generado entra al rastro de auditoría.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.intel.snapshot import MODEL

MAX_USES = 3
MAX_TOKENS = 1024

# El único formato que la API documenta y ejemplifica para `page_age`
# ("April 30, 2025"). No hay garantía de que sea el único que el proveedor
# produzca: ante cualquier otra forma, `parse_page_age` rechaza en vez de
# adivinar.
_PAGE_AGE_FORMAT = "%B %d, %Y"


class SearchError(Exception):
    """El proveedor no devolvió resultados utilizables."""


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Un resultado tal como lo devolvió la herramienta, sin interpretar."""

    url: str
    title: str
    page_age: str | None  # `None` cuando la fuente no declara fecha


class Searcher(Protocol):
    """Una consulta y una lista de fuentes.

    Sin historial y sin salida de texto a propósito: lo que este puerto entrega
    son **fuentes**, no un análisis. Un puerto que devolviera prosa invitaría a
    persistirla, y la prosa generada no pertenece al rastro de auditoría.
    """

    def search(
        self, query: str, allowed_domains: frozenset[str]
    ) -> tuple[SearchResult, ...]: ...


@dataclass
class AnthropicSearcher:
    """Adaptador de la herramienta de búsqueda web de la API de Mensajes.

    Import perezoso, igual que `GeminiEmbedder` y `AnthropicNarrator`: el módulo
    se importa —y los tests corren— sin clave configurada.

    `allowed_domains` se pasa a la herramienta para no pagar por resultados que
    igual se van a descartar. **No sustituye a `governance.enforce`**: es un
    recorte del lado del proveedor, y `blocked_domains` no puede ir junto con él
    —los dos en la misma petición devuelven 400—.
    """

    api_key: str | None = None
    model: str = MODEL
    max_uses: int = MAX_USES
    _client: Any = field(default=None, init=False, repr=False)

    def _cliente(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic
            from langsmith.wrappers import wrap_anthropic

            clave = self.api_key or settings.anthropic_api_key
            if not clave:
                raise SearchError(
                    "falta `ANTHROPIC_API_KEY`. Es la única variable de entorno "
                    "del proveedor: el modelo y la plantilla de query viven en "
                    "código, porque cambiarlos por `env` haría mentir a "
                    "`threat_intel_version`."
                )
            # Mismo criterio que `AnthropicNarrator._cliente`: envolver es
            # no-op sin `LANGSMITH_TRACING` en `os.environ`.
            self._client = wrap_anthropic(Anthropic(api_key=clave))
        return self._client

    def search(
        self, query: str, allowed_domains: frozenset[str]
    ) -> tuple[SearchResult, ...]:
        respuesta = self._cliente().messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": query}],
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": self.max_uses,
                    # Dominios pelados, sin esquema: es el formato que la API
                    # exige y el mismo que produce `normalize_allowlist`.
                    "allowed_domains": sorted(allowed_domains),
                }
            ],
        )
        return _extraer(respuesta)


def _extraer(respuesta: Any) -> tuple[SearchResult, ...]:
    """Los bloques de resultado, ignorando el texto del modelo.

    Defensivo con `getattr`: un bloque de error de búsqueda tiene la misma
    posición y otro contenido, y una versión nueva del SDK puede agregar bloques
    que este código no conoce. Lo desconocido se saltea, no rompe.
    """
    salida: list[SearchResult] = []

    for bloque in getattr(respuesta, "content", []) or []:
        if getattr(bloque, "type", None) != "web_search_tool_result":
            continue

        contenido = getattr(bloque, "content", None)
        if not isinstance(contenido, list):
            # `web_search_tool_result_error`: la búsqueda falló del lado del
            # proveedor. No es excepción —el script sigue con los otros emisores—.
            continue

        for item in contenido:
            url = getattr(item, "url", None)
            titulo = getattr(item, "title", None)
            if not url or not titulo:
                continue
            salida.append(
                SearchResult(
                    url=url,
                    title=titulo,
                    page_age=getattr(item, "page_age", None),
                )
            )

    return tuple(salida)


def parse_page_age(page_age: str | None) -> date | None:
    """La fecha de publicación de la fuente, o `None` si no se puede leer.

    Estricto a propósito: adivinar un formato distinto al documentado
    arriesga leer mal la fecha que evalúa la ventana de 24h de FP-10. El
    llamador (`fetch_threat_intel.py`) rechaza la fila cuando esto da `None`.
    """
    if not page_age:
        return None

    try:
        return datetime.strptime(page_age.strip(), _PAGE_AGE_FORMAT).date()
    except ValueError:
        return None


@dataclass
class FakeSearcher:
    """Doble para tests y para correr el build sin clave.

    Lleva **su propia versión** en los resultados que produce el script, para que
    un snapshot de prueba no pueda confundirse con dato real.
    """

    results: tuple[SearchResult, ...] = ()

    def search(
        self, query: str, allowed_domains: frozenset[str]
    ) -> tuple[SearchResult, ...]:
        return self.results
