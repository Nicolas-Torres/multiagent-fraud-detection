"""Indicadores de compromiso: consulta y caché.

Insumo de FP-10 y del bloque de citación externa del Threat Intel Agent.

## Por qué no reusa `BlacklistCache`

Comparten el patrón —caché por proceso, TTL más `invalidate()`, inyectada en
`GraphContext`— y no la implementación. La lista negra cachea un `frozenset[str]`
y su consulta es `in`; acá el lookup necesita la ventana temporal, así que lo que
se cachea es un **índice** `(tipo, valor) → observaciones`.

Dos consumidores con el mismo patrón y formas distintas no comparten código:
extraer una caché genérica ahora obligaría a parametrizar el tipo del valor, la
consulta y la clave, y el resultado sería más largo que las dos juntas.

## Por qué TTL y no sólo invalidación

Igual que en la lista negra: con N réplicas, invalidar limpia la que recibió la
escritura y las demás siguen sirviendo el corpus viejo sin que nada falle. El TTL
da obsolescencia acotada sin coordinación. Un minuto de retraso es aceptable
porque el snapshot ya tiene la antigüedad de su último `fetch`, medida en horas.
"""

import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from multiagent_fraud_detection.db.models import ThreatIndicator
from multiagent_fraud_detection.enums import IndicatorType
from multiagent_fraud_detection.intel.snapshot import SNAPSHOT_VERSION

DEFAULT_TTL_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class Indicator:
    """Una observación, desacoplada del ORM.

    Los predicados no ven objetos de SQLAlchemy: en async, una instancia leída
    fuera de su sesión lanza `MissingGreenlet` al tocar cualquier atributo no
    cargado. Copiar a un valor inmutable en el momento de la lectura hace
    imposible ese error, y de paso deja los predicados testeables sin base.
    """

    indicator_type: IndicatorType
    value: str
    observed_at: datetime
    retrieved_at: datetime
    source_url: str
    summary: str


#: `(tipo, valor) → observaciones`, ordenadas de más reciente a más antigua.
IndicatorIndex = Mapping[tuple[IndicatorType, str], tuple[Indicator, ...]]

EMPTY_INDEX: IndicatorIndex = {}


async def active_indicators(session: AsyncSession) -> IndicatorIndex:
    """El corpus vigente, indexado.

    El `WHERE snapshot_version = SNAPSHOT_VERSION` **no es un filtro sino un
    invariante de corrección** (ADR-0014): sin él, un veredicto podría consultar
    dos generaciones a la vez y el sello de la decisión diría una sola.
    """
    stmt = (
        select(ThreatIndicator)
        .where(
            ThreatIndicator.active,
            ThreatIndicator.snapshot_version == SNAPSHOT_VERSION,
        )
        .order_by(ThreatIndicator.observed_at.desc())
    )

    indice: dict[tuple[IndicatorType, str], list[Indicator]] = defaultdict(list)
    for fila in (await session.scalars(stmt)).all():
        indice[(fila.indicator_type, fila.value)].append(
            Indicator(
                indicator_type=fila.indicator_type,
                value=fila.value,
                observed_at=fila.observed_at,
                retrieved_at=fila.retrieved_at,
                source_url=fila.source_url,
                summary=fila.summary,
            )
        )

    # `dict` plano y tuplas: un `defaultdict` que se escapa a los predicados
    # crearía claves vacías al consultarlo, y una clave presente con lista vacía
    # es indistinguible de un indicador que no existe.
    return {clave: tuple(obs) for clave, obs in indice.items()}


@dataclass
class IndicatorCache:
    """Caché por proceso, con vencimiento. Vive en `GraphContext`."""

    ttl_seconds: float = DEFAULT_TTL_SECONDS
    _valor: IndicatorIndex | None = field(default=None, repr=False)
    _cargado_en: float = field(default=0.0, repr=False)

    def invalidate(self) -> None:
        """Fuerza la próxima lectura. Lo llama el alta desde el dashboard."""
        self._valor = None

    @property
    def vencida(self) -> bool:
        # `>=` y no `>`: con `>`, un `ttl_seconds=0` —que debe significar "no
        # cachear"— no vence si el reloj no avanzó entre dos llamadas. En Windows
        # el temporizador ronda los 15 ms y dos lecturas seguidas devuelven el
        # mismo valor. El síntoma sería verde en CI y rojo en la máquina de quien
        # programa, y un test que sólo falla local se termina ignorando.
        return (
            self._valor is None
            or (time.monotonic() - self._cargado_en) >= self.ttl_seconds
        )

    async def get(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> IndicatorIndex:
        if not self.vencida:
            return self._valor  # type: ignore[return-value]

        async with session_factory() as session:
            self._valor = await active_indicators(session)

        self._cargado_en = time.monotonic()
        return self._valor
