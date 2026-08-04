"""Lista negra de comercios: consulta y caché.

Insumo de FP-07, y el único dato de gobernanza que la ola 1 del grafo necesita.

## Por qué hay caché

Son unidades de filas y el grafo la lee **una vez por transacción**. Sin caché,
evaluar el dataset completo son 7 000 consultas para leer la misma lista. El §4
del contrato ya lo había resuelto así.

## Por qué TTL y no sólo invalidación

El contrato dice *"cacheada en memoria con invalidación al escribir"*, y eso
asume un proceso. Con N réplicas, invalidar limpia **la que recibió la
escritura**; las demás siguen sirviendo la lista vieja sin que nada falle.

El TTL da obsolescencia **acotada** en todas las réplicas sin coordinación entre
ellas. `invalidate()` se conserva porque la réplica que atiende un alta desde el
dashboard debería verla al instante —es la que le responde al humano que la dio—.

Un minuto de retraso al **agregar** un comercio es aceptable; al **retirarlo**
también, porque la baja es lógica y el caso congela su evidencia en `signals`.
"""

import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from multiagent_fraud_detection.db.models import MerchantBlacklist

DEFAULT_TTL_SECONDS = 60.0


async def active_merchants(session: AsyncSession) -> frozenset[str]:
    """Los comercios vigentes. `active=False` es baja lógica: no cuenta."""
    stmt = select(MerchantBlacklist.merchant_id).where(MerchantBlacklist.active)
    return frozenset((await session.scalars(stmt)).all())


@dataclass
class BlacklistCache:
    """Caché por proceso, con vencimiento.

    Vive en `GraphContext` y no como global de módulo: un global obligaría a
    resetear estado compartido entre tests y escondería la dependencia. Acá es
    explícita, se inyecta, y un test puede pasar la suya.
    """

    ttl_seconds: float = DEFAULT_TTL_SECONDS
    _valor: frozenset[str] | None = field(default=None, repr=False)
    _cargado_en: float = field(default=0.0, repr=False)

    def invalidate(self) -> None:
        """Fuerza la próxima lectura. Lo llama el alta desde el dashboard."""
        self._valor = None

    @property
    def vencida(self) -> bool:
        # `>=` y no `>`: con `>`, un `ttl_seconds=0` —que debe significar "no
        # cachear"— no vence si el reloj no avanzó entre dos llamadas. En Linux
        # `monotonic()` tiene resolución de nanosegundos y siempre avanza; en
        # Windows el temporizador por defecto ronda los 15 ms, así que dos
        # lecturas seguidas devuelven el mismo valor y la caché nunca expiraba.
        #
        # El síntoma sería el peor posible: verde en el CI (Linux) y rojo en la
        # máquina de quien programa. Un test que solo falla local se termina
        # ignorando.
        return (
            self._valor is None
            or (time.monotonic() - self._cargado_en) >= self.ttl_seconds
        )

    async def get(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> frozenset[str]:
        if not self.vencida:
            return self._valor  # type: ignore[return-value]

        async with session_factory() as session:
            self._valor = await active_merchants(session)

        self._cargado_en = time.monotonic()
        return self._valor
