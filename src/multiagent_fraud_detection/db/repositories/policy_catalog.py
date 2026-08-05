"""El catálogo de políticas leído desde Postgres. Fase 3 de ADR-0007.

La segunda implementación de `CatalogSource`. Devuelve exactamente la misma forma
cruda que `FileCatalogSource` —`RawCatalog`— para que `build_catalog` sea una
sola pieza de código compartida. Si esta clase construyera `Policy`, el test que
afirma que archivo y base coinciden estaría comparando dos copias del mismo bug.

## Por qué es síncrona

El catálogo se lee **una vez por proceso**, no por caso: `GraphContext` lo toma
desde un `default_factory`, que no puede esperar una corrutina, y
`check_policies.py` corre sin event loop. Un puerto `async` obligaría a los dos a
arrastrar `asyncio` por una lectura que ocurre al arrancar.

El engine se crea y se descarta dentro de `fetch()`. Sostener un pool para una
lectura única cuesta más de lo que ahorra, y psycopg3 acepta la misma URL en modo
sync y async —el motivo por el que `migrations/env.py` también es síncrono—.

## Qué documento se lee cuando hay varias versiones

El archivo entrega una versión por política porque eso *es* la entrega. La tabla
acumula versiones, así que acá se toma la **más reciente por `policy_id`**.

La consecuencia es deseable y conviene verla de frente: si una vinculación apunta
a `2025.1` y el banco publicó `2025.2`, el texto que se lee es el nuevo, la huella
registrada deja de coincidir y la política sale `STALE`. Eso es precisamente lo
que ADR-0007 quiere poder detectar —una traducción hecha contra un texto que ya
no es el vigente— y no un artefacto de la consulta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.db.models import (
    BindingSet,
    FraudPolicy,
    PolicyBinding,
)
from multiagent_fraud_detection.domain.catalog import RawCatalog


class NoBindingSetError(Exception):
    """No hay set de vinculaciones que leer.

    Es un error y no un catálogo vacío a propósito: un motor que arranca sin
    catálogo no evalúa ninguna política, no dispara ninguna señal y manda todo a
    `ESCALATE_TO_HUMAN` — con la forma de un sistema que funciona.
    """


@dataclass(frozen=True, slots=True)
class DbCatalogSource:
    """Los registros crudos del catálogo, desde las tres tablas.

    `version=None` lee el set **activo**, que es el caso normal. Pasarla explícita
    permite leer un set candidato sin promoverlo: es lo que hace comparable una
    traducción nueva contra la vigente antes de activarla.
    """

    url: str | None = None
    version: str | None = None

    def fetch(self) -> RawCatalog:
        engine = create_engine(self.url or settings.database_url)
        try:
            with Session(engine) as session:
                return self.fetch_with(session)
        finally:
            engine.dispose()

    def fetch_with(self, session: Session) -> RawCatalog:
        """Igual que `fetch`, sobre una sesión que abre el llamador.

        Existe para que un smoke test o un script que ya tiene sesión no abra un
        segundo engine contra la misma base.
        """
        sobre = self._binding_set(session)

        # `DISTINCT ON` con el orden que decide el empate: la versión más
        # reciente de cada política. `created_at` primero porque es el hecho
        # —cuándo se publicó—; la versión desempata cuando dos entran en el mismo
        # commit, que es lo que hace el seed.
        documentos = session.scalars(
            select(FraudPolicy)
            .distinct(FraudPolicy.policy_id)
            .order_by(
                FraudPolicy.policy_id,
                FraudPolicy.created_at.desc(),
                FraudPolicy.version.desc(),
            )
        ).all()

        vinculaciones = session.scalars(
            select(PolicyBinding)
            .where(PolicyBinding.binding_set_version == sobre.version)
            .order_by(PolicyBinding.policy_id)
        ).all()

        # El texto vuelve a viajar bajo el nombre que declara el sobre —`rule`—,
        # no bajo el de la columna. `build_catalog` resuelve el campo por
        # `fingerprint_field`, así que lo que se firmó y lo que se lee tienen que
        # llamarse igual en las dos fuentes.
        campo = sobre.fingerprint_field

        return RawCatalog(
            documents=[
                {
                    "policy_id": d.policy_id,
                    "version": d.version,
                    campo: d.text,
                }
                for d in documentos
            ],
            header={
                "binding_set_version": sobre.version,
                "source_catalog": sobre.source_catalog,
                "fingerprint_algorithm": sobre.fingerprint_algorithm,
                "fingerprint_field": sobre.fingerprint_field,
                "reference_currency": sobre.reference_currency,
            },
            bindings=[self._binding(v) for v in vinculaciones],
        )

    # ----------------------------------------------------------------------- #

    def _binding_set(self, session: Session) -> BindingSet:
        stmt = select(BindingSet)
        stmt = (
            stmt.where(BindingSet.version == self.version)
            if self.version
            else stmt.where(BindingSet.active)
        )

        sobre = session.scalars(stmt).first()

        if sobre is None:
            que = f"el set {self.version!r}" if self.version else "ningún set activo"
            raise NoBindingSetError(
                f"no se encontró {que} en `binding_sets`. "
                f"¿Corriste `python scripts/seed.py`?"
            )

        # No hace falta verificar que haya uno solo: el índice parcial único
        # `uq_binding_sets_single_active` lo garantiza en la base. Chequearlo acá
        # sería reimplementar en Python una invariante que ya es estructural.
        return sobre

    @staticmethod
    def _binding(v: PolicyBinding) -> dict[str, Any]:
        return {
            "policy_id": v.policy_id,
            "source_version": v.source_version,
            "source_fingerprint": v.source_fingerprint,
            # `.value` y no el miembro: `RawCatalog` es la forma de entrega, y en
            # el archivo `action` es una cadena. Que el enum acepte su propio
            # miembro no es razón para que las dos fuentes difieran en el tipo.
            "action": v.action.value,
            "condition": v.condition,
            "excluded_reason": v.excluded_reason,
            "active": v.active,
            "bound_by": v.bound_by,
        }
