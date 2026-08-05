"""La query del RAG: de códigos de señal a texto.

## Por qué desde los códigos y no desde las descripciones

`Signal.description` lleva los valores observados —montos, horas, conteos—, así
que cada transacción produciría una cadena distinta y el caché no existiría: 7 000
llamadas al proveedor por corrida del harness, y un harness que deja de ser
offline. Los **códigos** son un vocabulario cerrado de catorce, así que las
queries posibles están acotadas por las combinaciones que el dataset produce, dos
órdenes de magnitud por debajo.

## Por qué el vocabulario se deriva del catálogo

Un código suelto no es buen texto para embeber: `DEVICE_VELOCITY` contra prosa
normativa en castellano recupera mal. Hace falta una frase, y la frase ya existe:
`Predicate.description`, que es **estática** —sale del decorador o de la primera
línea del docstring— a diferencia de `Signal.description`, que es la observación.

Recorriendo las condiciones del catálogo sale el mapa `código → frase` sin
escribir un diccionario paralelo. Eso importa: un diccionario a mano se
desincroniza el día que se agrega un predicado, y el síntoma sería que la query
pierde un término sin que nada falle.

El mapa depende del **catálogo**, no sólo de la biblioteca: sólo aparecen los
códigos alcanzables en el set de vinculaciones vigente, que son los que el motor
puede emitir.

## El caché

Vive en `GraphContext`, no como global de módulo, por el mismo motivo que
`BlacklistCache`: un global obligaría a resetear estado compartido entre tests y
escondería la dependencia.

Sin TTL, a diferencia del de la lista negra. La entrada no puede quedar obsoleta
por una escritura de otra réplica: la clave es un conjunto de códigos y el valor
es su embedding bajo `INDEX_VERSION`, y si la versión cambia cambia el proceso.
Lo que sí lo invalidaría es cambiar el modelo o la plantilla — y eso no ocurre en
caliente por definición.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from multiagent_fraud_detection.domain.catalog import PolicyCatalog

#: Señales que no describen la transacción y por lo tanto no deben orientar la
#: recuperación. `NO_CUSTOMER_PROFILE` dice que faltó con qué comparar: meterla
#: en la query traería políticas sobre perfiles en vez de sobre lo que pasó. Es
#: la misma exclusión que ya hace `risk_score`, por la misma razón de categoría.
NON_RETRIEVAL_CODES = frozenset({"NO_CUSTOMER_PROFILE"})


def code_vocabulary(catalog: PolicyCatalog) -> dict[str, str]:
    """`código de señal` → frase estática del predicado que lo emite.

    Se construye una vez por proceso, junto al catálogo. Si dos predicados
    emitieran el mismo código gana el primero en orden de política: el código es
    la unidad del vocabulario, no el predicado, y dos frases para un código serían
    ya un problema del catálogo.
    """
    vocabulario: dict[str, str] = {}

    for politica in catalog.policies:
        for paso in politica.condition:
            codigo = paso.predicate.signal_code(**paso.params)
            vocabulario.setdefault(codigo, paso.predicate.description)

    return vocabulario


def query_codes(codes: Iterable[str]) -> tuple[str, ...]:
    """Los códigos que entran a la query: sin repetir, sin los excluidos, ordenados.

    El orden es alfabético y no de emisión **a propósito**: dos casos con las
    mismas señales en distinto orden tienen que producir la misma query, o el
    caché falla y el proveedor devuelve dos vectores para lo mismo.
    """
    return tuple(sorted({c for c in codes if c not in NON_RETRIEVAL_CODES}))


def build_query(codes: Iterable[str], vocabulary: Mapping[str, str]) -> str:
    """El texto a embeber. Vacío si no quedó ningún código utilizable.

    Un código sin entrada en el vocabulario cae a su forma legible en vez de
    perderse: si alguien agrega un predicado y algo queda mal cableado, la query
    se degrada, no se calla.

    Las frases se limpian de su puntuación final antes de unirse. No es
    cosmética: el texto se embebe tal cual, y `"...ventana corta.. El
    dispositivo..."` mete ruido en el vector por un detalle de formato de los
    docstrings de los predicados.
    """
    frases = [
        vocabulary.get(codigo, codigo.replace("_", " ").lower()).strip().rstrip(".")
        for codigo in query_codes(codes)
    ]
    return ". ".join(f for f in frases if f)


@dataclass
class QueryCache:
    """Embeddings de query por combinación de códigos. Por proceso.

    Sin límite de tamaño: la clave es un subconjunto de un vocabulario cerrado de
    catorce, y en la práctica el dataset produce decenas de combinaciones. Un
    corpus que hiciera crecer el vocabulario haría crecer esto, y ese día el
    límite se agrega con un número medido en vez de inventado.
    """

    _valores: dict[tuple[str, ...], list[float]] = field(
        default_factory=dict, repr=False
    )

    def __len__(self) -> int:
        return len(self._valores)

    def get(self, codes: Iterable[str]) -> list[float] | None:
        return self._valores.get(query_codes(codes))

    def put(self, codes: Iterable[str], vector: list[float]) -> None:
        self._valores[query_codes(codes)] = vector
