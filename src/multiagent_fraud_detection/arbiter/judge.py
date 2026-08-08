"""El proveedor de juicio, detrás de un puerto. Tercer rol de generación del
sistema, junto a `Narrator` (texto libre) y `Searcher` (búsqueda).

## Por qué un puerto nuevo y no `Narrator`

El Arbiter necesita un `DecisionType` válido y un `float` acotado, no prosa a
parsear a mano — parsear texto libre para sacar una decisión reintroduciría
con una expresión regular el mismo riesgo que la salida estructurada existe
para evitar. Mismo criterio que separó `Embedder` de `Narrator`: puerto
distinto cuando la forma del contrato es distinta, aunque el proveedor de
abajo sea el mismo.

## El Arbiter lee `policy_id`, nunca los otorga

`ArbiterVerdict` no tiene ningún campo que nombre una política — la evidencia
y las políticas disparadas ya vienen resueltas por el motor
(`domain/engine.py`), y el Arbiter sólo elige `decision` de un enum cerrado.
Es la misma garantía que ya cumple `explainability`, aplicada a un campo
estructurado en vez de a prosa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, Field

from multiagent_fraud_detection.arbiter.prompt import MAX_TOKENS, MODEL
from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.enums import DecisionType


class JudgeError(Exception):
    """El proveedor no devolvió un veredicto utilizable."""


class ArbiterVerdict(BaseModel):
    decision: DecisionType
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)


class Judge(Protocol):
    """Un prompt de sistema y uno de usuario, un veredicto estructurado.

    Misma forma que `Narrator` en la superficie —sin historial, sin
    herramientas—, con la salida acotada a `ArbiterVerdict` en vez de a texto
    libre: fallar un veredicto bien tipado es más fácil de detectar que
    fallar en parsear texto libre a mano.
    """

    def judge(self, system: str, user: str) -> ArbiterVerdict: ...


@dataclass
class AnthropicJudge:
    """Adaptador de la API de Mensajes, con salida estructurada
    (`messages.parse`, contra `ArbiterVerdict`).

    Import perezoso, igual que `AnthropicNarrator`: el módulo se importa —y
    las constantes se leen, y los tests corren— sin la dependencia instalada
    ni clave configurada.
    """

    api_key: str | None = None
    model: str = MODEL
    max_tokens: int = MAX_TOKENS
    _client: Any = field(default=None, init=False, repr=False)

    def _cliente(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic

            clave = self.api_key or settings.anthropic_api_key
            if not clave:
                raise JudgeError(
                    "falta `ANTHROPIC_API_KEY`. Es la única variable de entorno "
                    "del proveedor: el modelo y el prompt viven en código, no "
                    "en `env`, para que la versión declarada en este módulo "
                    "no pueda mentir sobre qué los produjo."
                )
            self._client = Anthropic(api_key=clave)
        return self._client

    def judge(self, system: str, user: str) -> ArbiterVerdict:
        respuesta = self._cliente().messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=ArbiterVerdict,
        )

        veredicto = respuesta.parsed_output
        if veredicto is None:
            raise JudgeError("el proveedor no devolvió un veredicto estructurado")

        return veredicto


@dataclass(frozen=True, slots=True)
class FakeJudge:
    """Veredicto fijo y determinista, para tests y para el smoke sin red.

    **No es un fallback.** Si el proveedor falla en producción, lo que
    corresponde es escalar con el piso determinista —ver `decision_arbiter`—
    y no esto, que es reconociblemente artificial a propósito: si alguna vez
    apareciera en un veredicto real, se nota.
    """

    verdict: ArbiterVerdict = field(
        default_factory=lambda: ArbiterVerdict(
            decision=DecisionType.ESCALATE_TO_HUMAN,
            confidence=0.5,
            rationale="[veredicto de prueba]",
        )
    )

    def judge(self, system: str, user: str) -> ArbiterVerdict:
        return self.verdict
