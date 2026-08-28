"""Canal efímero de progreso en vivo (ADR-0018): qué nodo del grafo terminó,
para la demo del dashboard. Puramente en memoria — nunca toca Postgres,
nunca reemplaza a `GET /cases/{id}` como fuente de verdad del veredicto
(§7.3 del contrato: W2 sigue siendo el único punto que persiste el
resultado, y lo hace en un solo commit).

Un registro por proceso, no por réplica: con N réplicas cada una sólo ve el
progreso de los casos que ella misma corre. Aceptable a propósito — es un
agregado visual, no un dato que el sistema tenga que reconciliar entre
instancias.

Guarda también un historial corto por caso: el primer superstep del grafo
(reglas deterministas, sin LLM) suele terminar en milisegundos, antes de
que el `EventSource` del navegador siquiera termine el handshake -sin
historial esos nodos jamás llegan a mostrarse. `suscribirse` entrega el
historial acumulado hasta ese instante junto con la cola, de forma atómica
respecto al event loop (nada hace `await` entre leerlo y registrar la
cola), así que ningún nodo publicado después queda ni duplicado ni perdido
entre el historial y la cola.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from uuid import UUID

_suscriptores: dict[UUID, list[asyncio.Queue]] = defaultdict(list)
_historial: dict[UUID, list[str]] = defaultdict(list)

# Sentinel de cierre — un objeto propio, no `None` ni un string: un nodo
# real nunca puede confundirse con "se acabó".
FIN = object()


def suscribirse(case_id: UUID) -> tuple[asyncio.Queue, list[str]]:
    cola: asyncio.Queue = asyncio.Queue()
    _suscriptores[case_id].append(cola)
    return cola, list(_historial.get(case_id, ()))


def desuscribirse(case_id: UUID, cola: asyncio.Queue) -> None:
    colas = _suscriptores.get(case_id)
    if colas is None:
        return
    if cola in colas:
        colas.remove(cola)
    if not colas:
        _suscriptores.pop(case_id, None)


def publicar(case_id: UUID, nodo: str) -> None:
    _historial[case_id].append(nodo)
    for cola in _suscriptores.get(case_id, ()):
        cola.put_nowait(nodo)


def cerrar(case_id: UUID) -> None:
    """Notifica el fin a los suscriptores que haya en este instante y
    limpia el registro. Si el caso revienta, el `finally` de quien invoca
    el grafo llama a esto igual — ningún suscriptor queda colgado."""
    for cola in _suscriptores.get(case_id, ()):
        cola.put_nowait(FIN)
    _suscriptores.pop(case_id, None)
    _historial.pop(case_id, None)
