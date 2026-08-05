from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from multiagent_fraud_detection.db.base import Base


class BindingSet(Base):
    """El encabezado del sobre de vinculación. Es `policy_catalog_version`.

    Lo que hoy son las claves sueltas de `policy_bindings_2025.1.json` antes de
    la lista: la versión del set, contra qué catálogo se tradujo, con qué
    algoritmo y sobre qué campo se calculó la huella, y en qué moneda están los
    umbrales.

    **Por qué es una tabla y no metadatos repetidos en cada vinculación.** Son
    atributos del **acto de traducir**, no de cada traducción: las once
    vinculaciones de `2025.1-b1` comparten los cinco valores. Repetirlos por fila
    permitiría que dos vinculaciones del mismo set declararan algoritmos de
    huella distintos, que es un estado sin significado.

    Es también lo que la decisión sella en `decisions.policy_catalog_version`: el
    motor lee el set activo y guarda su `version`.

    **A lo sumo un set activo**, garantizado por un índice parcial único y no por
    `CheckConstraint` —punto ciego de `--autogenerate`—. El índice es sobre la
    propia columna booleana con predicado `WHERE active`: entre las filas activas
    el valor de `active` tiene que ser único, y como sólo puede valer `true`,
    hay a lo sumo una. Un `CREATE UNIQUE INDEX ... ((true))` diría lo mismo con
    una expresión constante; esto lo dice sin ninguna.

    **El default de `active` es `false`.** Cargar un set nuevo no lo promueve:
    activarlo es un acto aparte, y el default seguro es el que no cambia lo que
    el motor está evaluando.
    """

    __tablename__ = "binding_sets"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)

    # Qué archivo o catálogo de documentos se tradujo. Es trazabilidad, no FK:
    # apunta a un artefacto de entrega, no a una fila.
    source_catalog: Mapped[str] = mapped_column(String)

    fingerprint_algorithm: Mapped[str] = mapped_column(String(16))

    # Qué campo del documento se hasheó, con el nombre que tenía en el formato
    # de entrega (`rule`). La columna de `fraud_policies` se llama `text`; el
    # nombre de acá registra contra qué se firmó, no dónde se guarda.
    fingerprint_field: Mapped[str] = mapped_column(String(32))

    # Moneda de los umbrales de las condiciones. Los montos se convierten a
    # ésta antes de comparar.
    reference_currency: Mapped[str] = mapped_column(String(3))

    active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index(
            "uq_binding_sets_single_active",
            "active",
            unique=True,
            postgresql_where=text("active"),
        ),
    )
