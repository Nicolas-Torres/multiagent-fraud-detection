"""Exporta el modelo de datos como diagrama ER, derivado de la metadata.

    uv run python scripts/export_data_model_diagram.py
    uv run python scripts/export_data_model_diagram.py --check   # gate, sin red

## Por qué esto reemplaza a `modelo-datos.drawio`

El diagrama dibujado a mano se quedó dos etapas atrás —seis tablas de doce— sin
que nadie lo notara en tres cierres de rama, a pesar de que la convención dice
que se documenta al cerrar cada etapa. La topología del grafo nunca derivó, y la
diferencia no es la disciplina: es que una se **genera** y un guard la vigila.

Un diagrama derivado de `Base.metadata` no puede atrasarse. Y deja de ser una
ilustración para pasar a ser evidencia: muestra el modelo que está en el código,
no el que alguien recuerda.

## Dos mejoras sobre `export_graph_diagram.py`

**Se escribe también el `.mmd`.** Un PNG es un blob: el diff dice "cambió" y nada
más. El fuente Mermaid es texto, se revisa en el PR y muestra exactamente qué
columna entró. El PNG queda para el README.

**El guard compara el fuente, no el PNG.** Si el modelo no cambió, el script
termina sin llamar a mermaid.ink. El de topología hace la llamada siempre y
compara después.

`--check` retorna distinto de cero si el modelo cambió sin regenerar el diagrama.
No usa red, así que sirve como gate de CI al lado de `alembic check` — que cubre
lo mismo del lado de las migraciones.

## Sobre los tipos

Mermaid no acepta paréntesis ni comas en el tipo de un atributo, así que
`NUMERIC(12, 2)` se escribe `NUMERIC_12_2`. Se prefiere eso a recortar el tipo a
`NUMERIC`: la precisión del dinero es justamente lo que el diagrama tiene que
mostrar.
"""

import argparse
import re
import sys
from pathlib import Path

from sqlalchemy import UniqueConstraint

from multiagent_fraud_detection.db.base import Base

# El import registra las doce tablas en la metadata. Sin él, el diagrama sale
# vacío y el guard diría "sin cambios" con toda seguridad.
import multiagent_fraud_detection.db.models  # noqa: F401

DIAGRAMS = Path(__file__).resolve().parents[1] / "docs" / "diagrams"
MMD_PATH = DIAGRAMS / "data_model.mmd"
PNG_PATH = DIAGRAMS / "data_model.png"


def _tipo(columna) -> str:
    """El tipo SQL en la forma que Mermaid acepta como token."""
    crudo = str(columna.type)
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]", "_", crudo)).strip("_")


def _llaves(tabla, columna) -> str:
    """Las marcas de clave, **separadas por coma**: Mermaid lo exige así.

    `UNIQUE` se busca por los dos caminos por los que SQLAlchemy lo expresa:
    `Column(unique=True)`, que no crea un `UniqueConstraint` en la metadata, y
    la restricción declarada en `__table_args__`. Con uno solo de los dos,
    `cases.transaction_id` sale sin marca — y ese UNIQUE es lo que sostiene la
    idempotencia del `POST /cases`.
    """
    marcas = []
    if columna.primary_key:
        marcas.append("PK")
    if columna.foreign_keys:
        marcas.append("FK")

    # Por identidad y no con `in`: `ColumnCollection.__contains__` espera una
    # cadena, y pasarle el objeto columna lanza `ArgumentError`. Comparar con
    # `is` no depende de si la clave del atributo coincide con el nombre.
    unica = bool(columna.unique) or any(
        any(col is columna for col in c.columns)
        for c in tabla.constraints
        if isinstance(c, UniqueConstraint)
    )
    if unica and not columna.primary_key:
        marcas.append("UK")

    return ", ".join(marcas)


def _cardinalidad(tabla, columnas_fk: list[str]) -> str:
    """`1:1` cuando las columnas de la FK son la PK entera.

    Es el patrón de `decisions` y `human_resolutions`: PK compartida con `cases`,
    que da el 1:1 sin constraint extra. Se deriva en vez de anotarse.
    """
    pk = sorted(c.name for c in tabla.primary_key.columns)
    return "||--||" if sorted(columnas_fk) == pk else "||--o{"


def build_mermaid() -> str:
    lineas = ["erDiagram"]

    for tabla in Base.metadata.sorted_tables:
        lineas.append(f"    {tabla.name} {{")
        for columna in tabla.columns:
            marcas = _llaves(tabla, columna)
            nulo = "" if columna.nullable is False else '"NULL"'
            sufijo = " ".join(x for x in (marcas, nulo) if x)
            lineas.append(
                f"        {_tipo(columna)} {columna.name}"
                + (f" {sufijo}" if sufijo else "")
            )
        lineas.append("    }")

    lineas.append("")

    # Las relaciones salen de las FK declaradas, incluidas las compuestas: una
    # FK compuesta es UNA relación, no dos.
    # `foreign_key_constraints` es un **set**: su orden de iteracion depende del
    # hash de los objetos y cambia entre procesos. Sin ordenar, cada corrida
    # emite las relaciones en otro orden y el fuente nunca coincide consigo
    # mismo —diff espurio garantizado, y el guard gritando siempre—.
    #
    # El orden externo lo da `sorted_tables`, que si es determinista.
    vistas: set[tuple[str, str, str]] = set()
    for tabla in Base.metadata.sorted_tables:
        restricciones = sorted(
            tabla.foreign_key_constraints,
            key=lambda fk: (
                fk.referred_table.name,
                tuple(c.name for c in fk.columns),
            ),
        )
        for fk in restricciones:
            locales = [c.name for c in fk.columns]
            padre = fk.referred_table.name
            clave = (padre, tabla.name, ",".join(sorted(locales)))
            if clave in vistas:
                continue
            vistas.add(clave)
            lineas.append(
                f"    {padre} {_cardinalidad(tabla, locales)} {tabla.name} : "
                f'"{", ".join(locales)}"'
            )

    return "\n".join(lineas) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--check",
        action="store_true",
        help="retorna 1 si el diagrama no refleja el modelo; no usa red",
    )
    args = ap.parse_args()

    mermaid = build_mermaid()
    tablas = len(Base.metadata.sorted_tables)
    vigente = MMD_PATH.exists() and MMD_PATH.read_text(encoding="utf-8") == mermaid

    if args.check:
        if vigente:
            print(f"al día: {MMD_PATH.name} ({tablas} tablas)")
            return 0
        print(
            f"DESACTUALIZADO: el modelo tiene {tablas} tablas y "
            f"{MMD_PATH.name} no coincide.\n"
            f"Corré `uv run python scripts/export_data_model_diagram.py`.",
            file=sys.stderr,
        )
        return 1

    if vigente and PNG_PATH.exists():
        print(f"sin cambios: {MMD_PATH.name} ({tablas} tablas)")
        return 0

    DIAGRAMS.mkdir(parents=True, exist_ok=True)
    MMD_PATH.write_text(mermaid, encoding="utf-8")
    print(f"escrito: {MMD_PATH.name} ({tablas} tablas)")

    # El import va acá y no arriba: `--check` no debe necesitar la dependencia
    # de render ni la red.
    from langchain_core.runnables.graph_mermaid import draw_mermaid_png

    png = draw_mermaid_png(mermaid_syntax=mermaid, background_color="white")
    PNG_PATH.write_bytes(png)
    print(f"escrito: {PNG_PATH.name} ({len(png):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
