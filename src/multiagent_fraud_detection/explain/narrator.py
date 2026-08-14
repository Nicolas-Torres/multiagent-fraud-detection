"""El proveedor de generación, detrás de un puerto. Segundo proveedor del sistema.

Simetría deliberada con `retrieval/embeddings.py`: mismo patrón de puerto, mismo
motivo. Cambiar de proveedor tiene que ser un adaptador y una versión nueva, no
una reescritura.

## Dos proveedores, dos roles

| Proveedor | Rol | Sello |
|---|---|---|
| Gemini | recuperación (embeddings) | `retrieval_index_version` |
| Anthropic | generación (explicación) | `explanation_prompt_version` |

Es la división que §1.4 del contrato declara, y ahora los dos tienen consumidor
real. También es lo que hace comparable el costo y la latencia de cada uno para
el entregable 2.

## La asimetría que importa

El riesgo central de ADR-0012 —que el proveedor actualice el modelo del lado del
servidor sin cambiar el nombre, y los vectores dejen de ser reproducibles— **no
aplica de este lado**. Desde la generación 4.6, los IDs de modelo de Anthropic
son fijos: el ID canónico apunta a un snapshot que no se actualiza, y una versión
nueva sale con un ID nuevo.

Así que el segmento de modelo de `PROMPT_VERSION` es una garantía del proveedor.
Lo que sigue siendo responsabilidad nuestra es el otro segmento: editar el prompt
sin subir la generación produce textos nuevos bajo una versión vieja, y ninguna
consulta lo detecta.

## El texto generado no se evalúa acá

Los gates determinísticos del proyecto —`check_policies`, `check_retrieval`—
tienen que dar el mismo número dos veces, y una salida de LLM no lo hace. La
evaluación de la explicación es LLM-as-judge, que ADR-0013 pone en un carril
aparte: reporta, no bloquea.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.explain.customer import MAX_TOKENS, MODEL


class NarrationError(Exception):
    """El proveedor no devolvió texto utilizable."""


class Narrator(Protocol):
    """Un prompt de sistema y uno de usuario, un texto.

    Sin historial y sin herramientas a propósito: redactar una explicación es
    una operación sin estado, y un puerto que aceptara conversación invitaría a
    darle al modelo un rol que no tiene.
    """

    def narrate(self, system: str, user: str) -> str: ...


@dataclass
class AnthropicNarrator:
    """Adaptador de la API de Mensajes.

    Import perezoso, igual que `GeminiEmbedder`: el módulo se importa —y las
    constantes se leen, y los tests corren— sin la dependencia instalada ni clave
    configurada.
    """

    api_key: str | None = None
    model: str = MODEL
    max_tokens: int = MAX_TOKENS
    _client: Any = field(default=None, init=False, repr=False)

    def _cliente(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic
            from langsmith.wrappers import wrap_anthropic

            clave = self.api_key or settings.anthropic_api_key
            if not clave:
                raise NarrationError(
                    "falta `ANTHROPIC_API_KEY`. Es la única variable de entorno "
                    "del proveedor: el modelo y el prompt viven en código, "
                    "porque cambiarlos por `env` haría mentir a "
                    "`explanation_prompt_version`."
                )
            # No-op si `LANGSMITH_TRACING` no esta en `os.environ`
            # (`config.settings` lo propaga sólo cuando hay clave y flag
            # encendida) — envolver siempre es más simple que duplicar ese
            # chequeo acá.
            self._client = wrap_anthropic(Anthropic(api_key=clave))
        return self._client

    def narrate(self, system: str, user: str) -> str:
        respuesta = self._cliente().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )

        texto = "".join(
            bloque.text for bloque in respuesta.content if bloque.type == "text"
        ).strip()

        if not texto:
            raise NarrationError("el proveedor devolvió una respuesta sin texto")

        return texto


@dataclass(frozen=True, slots=True)
class FakeNarrator:
    """Texto fijo y determinista, para tests y para el smoke sin red.

    **No es un fallback.** Si el proveedor falla en producción, lo que
    corresponde es la plantilla de `customer.py` —redactada para ser leída por
    una persona— y no esto, que es reconociblemente artificial a propósito: si
    alguna vez apareciera en un mensaje real, se nota.
    """

    texto: str = "[explicación de prueba]"

    def narrate(self, system: str, user: str) -> str:
        return self.texto
