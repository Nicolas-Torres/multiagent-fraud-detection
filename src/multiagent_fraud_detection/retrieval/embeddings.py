"""El proveedor de embeddings, detrás de un puerto. ADR-0012.

Acá viven las cuatro cosas que `index_version` sella —modelo, dimensión,
plantillas de prompt y, por importación, la estrategia de chunking— y la cadena
que las declara. Están juntas porque la cadena se **compone** de ellas: cambiar
el modelo o una plantilla mueve `INDEX_VERSION` en el mismo commit, sin que nadie
tenga que acordarse de actualizarla.

## La instrucción de tarea va en el texto

`gemini-embedding-2` no acepta `task_type`. Donde `-001` recibía
`RETRIEVAL_DOCUMENT` / `RETRIEVAL_QUERY` como argumento, el modelo 2 espera la
instrucción dentro del prompt, con formato asimétrico: prefijo de tarea del lado
de la consulta, estructura `title | text` del lado del documento.

La consecuencia práctica es que **la plantilla es un parámetro de derivación**.
Editarla cambia los vectores igual que cambiar el modelo, y por eso vive en este
módulo y no en el indexador.

## Por qué el puerto embebe **un** texto y no una lista

No es una simplificación: es la forma de hacer irrepresentable un fallo. Con
varias entradas sueltas, el modelo 2 devuelve **un solo embedding agregado** en
vez de uno por entrada — sin error, sin excepción. Un índice construido así tiene
todas sus filas apuntando al mismo punto y devuelve resultados plausibles y
absurdos.

Con la firma `embed(text) -> vector` ese modo no se puede invocar por accidente.
Con once documentos el costo es una llamada por chunk, que además es lo que hace
verificable el resultado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.db.models.policy_chunk import EMBEDDING_DIMENSIONS

# --------------------------------------------------------------------------- #
# Parámetros de derivación — los cuatro suben `index_version`
# --------------------------------------------------------------------------- #

MODEL = "gemini-embedding-2"

DIMENSIONS = EMBEDDING_DIMENSIONS

# Formato asimétrico de recuperación. `title: none` porque las políticas no
# tienen título: poner el `policy_id` ahí inyectaría un identificador que la
# query —armada desde códigos de señal— nunca va a contener.
DOCUMENT_TEMPLATE = "title: none | text: {content}"
QUERY_TEMPLATE = "task: search result | query: {content}"

# Qué plantilla se aplicó al indexar. Antes este segmento nombraba el `task_type`;
# con la instrucción adentro del prompt nombra la plantilla.
TEMPLATE_TAG = "doc"

# Lo único a criterio humano: sube cuando cambia algo que los otros tres
# segmentos no muestran —la estrategia de chunking, por ejemplo—.
GENERATION = 1

INDEX_VERSION = f"{MODEL}:{DIMENSIONS}:{TEMPLATE_TAG}:{GENERATION}"


def format_document(content: str) -> str:
    return DOCUMENT_TEMPLATE.format(content=content)


def format_query(content: str) -> str:
    return QUERY_TEMPLATE.format(content=content)


# --------------------------------------------------------------------------- #
# El puerto
# --------------------------------------------------------------------------- #


class EmbeddingError(Exception):
    """El proveedor no devolvió un vector utilizable."""


class Embedder(Protocol):
    """Un texto, un vector. Ver el encabezado: la firma es la garantía."""

    def embed(self, text: str) -> list[float]: ...


@dataclass
class GeminiEmbedder:
    """Adaptador de `gemini-embedding-2`.

    El import de `google.genai` es perezoso para que este módulo se pueda
    importar —y las constantes leerse, y los tests correr— sin la dependencia
    instalada ni clave configurada.
    """

    api_key: str | None = None
    model: str = MODEL
    dimensions: int = DIMENSIONS
    _client: Any = field(default=None, init=False, repr=False)

    def _cliente(self) -> Any:
        if self._client is None:
            from google import genai

            clave = self.api_key or settings.gemini_api_key
            if not clave:
                raise EmbeddingError(
                    "falta `GEMINI_API_KEY`. Es la única variable de entorno del "
                    "proveedor: el modelo y la dimensión viven en código, porque "
                    "cambiarlos por `env` haría mentir a `index_version`."
                )
            self._client = genai.Client(api_key=clave)
        return self._client

    def embed(self, text: str) -> list[float]:
        from google.genai import types

        resultado = self._cliente().models.embed_content(
            model=self.model,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=self.dimensions),
        )

        # Desempaquetado de un elemento, y no `resultado.embeddings[0]`: si el
        # proveedor devolviera dos vectores —o ninguno— esto **levanta** en vez
        # de tomar el primero en silencio. Es la guarda del modo agregado.
        try:
            [embedding] = resultado.embeddings
        except ValueError as e:
            raise EmbeddingError(
                f"se esperaba exactamente un embedding y llegaron "
                f"{len(resultado.embeddings or [])}"
            ) from e

        valores = list(embedding.values)

        if len(valores) != self.dimensions:
            raise EmbeddingError(
                f"el proveedor devolvió {len(valores)} dimensiones y la columna "
                f"espera {self.dimensions}"
            )

        return valores


@dataclass(frozen=True, slots=True)
class FakeEmbedder:
    """Vectores deterministas desde un hash del texto. **No es un fallback.**

    Existe para poder verificar la idempotencia de la reindexación sin gastar
    cuota ni depender de la red: reindexar dos veces tiene que dejar la misma
    cantidad de filas, y eso no necesita vectores reales.

    Lo que impide que se cuele en un índice de verdad no es la disciplina: es
    `INDEX_VERSION`. `index_policies.py --fake` escribe bajo `fake:...`, así que
    sus filas no pueden confundirse con las buenas ni ser leídas por una búsqueda
    que filtra por la versión vigente. El mismo mecanismo que ADR-0012 §6 usa
    contra las generaciones viejas sirve contra esta.
    """

    dimensions: int = DIMENSIONS

    def embed(self, text: str) -> list[float]:
        import hashlib
        import struct

        # Un flujo de bytes determinista y arbitrariamente largo desde el texto.
        crudo = b""
        semilla = text.encode("utf-8")
        contador = 0
        while len(crudo) < self.dimensions * 4:
            crudo += hashlib.sha256(semilla + str(contador).encode()).digest()
            contador += 1

        valores = [
            struct.unpack("<i", crudo[i * 4 : i * 4 + 4])[0] / 2**31
            for i in range(self.dimensions)
        ]

        # Normalizado, como los vectores reales: el modelo auto-normaliza las
        # dimensiones truncadas, y un fake sin normalizar daría distancias
        # coseno con otra escala.
        norma = sum(v * v for v in valores) ** 0.5
        return [v / norma for v in valores]


FAKE_INDEX_VERSION = f"fake:{DIMENSIONS}:{TEMPLATE_TAG}:{GENERATION}"
