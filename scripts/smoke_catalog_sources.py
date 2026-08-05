"""Compara el catálogo leído del archivo contra el leído de Postgres.

    uv run python scripts/smoke_catalog_sources.py

`check_policies.py --source=db` ya prueba lo mismo de forma más fuerte —7 000
transacciones evaluadas con el catálogo de la base—, pero cuando falla dice
*cuántas* filas discrepan, no *qué* política quedó distinta. Esto es el
diagnóstico: compara los dos `PolicyCatalog` campo por campo.

## Por qué es un script y no un test de pytest

La suite corre **sin Postgres**: es lo que hace que el gate de CI sea de segundos
y no arrastre un servicio. Toda verificación que necesita base vive en
`scripts/smoke_*.py`, igual que `smoke_seed.py` y `smoke_persistence.py`. El día
que el job de CI levante Postgres para `alembic check` —§1.6 del contrato ya lo
planea— esto se vuelve una fixture y las comparaciones se vuelven `assert`.

## Qué revela una discrepancia

Que la base y `data/policies/` divergieron. La causa más probable no es un bug de
`DbCatalogSource` sino un seed que no se volvió a correr después de editar un
JSON. La segunda es real y vale la pena: el texto de una política cambió sin que
subiera su versión — la deuda declarada de la etapa.
"""

import sys

from multiagent_fraud_detection.db.repositories.policy_catalog import DbCatalogSource
from multiagent_fraud_detection.domain.catalog import (
    FileCatalogSource,
    PolicyCatalog,
    build_catalog,
)

from _dataset import DATA_DIR

POLICIES = DATA_DIR / "policies"

CAMPOS = ("version", "text", "state", "action", "condition", "excluded_reason", "bound_by")


def comparar(archivo: PolicyCatalog, base: PolicyCatalog) -> list[str]:
    problemas: list[str] = []

    if archivo.version != base.version:
        problemas.append(
            f"binding_set_version: archivo={archivo.version!r} base={base.version!r}"
        )

    if archivo.reference_currency != base.reference_currency:
        problemas.append(
            f"reference_currency: archivo={archivo.reference_currency!r} "
            f"base={base.reference_currency!r}"
        )

    por_id_a = {p.policy_id: p for p in archivo.policies}
    por_id_b = {p.policy_id: p for p in base.policies}

    for pid in sorted(set(por_id_a) - set(por_id_b)):
        problemas.append(f"{pid}: está en el archivo y no en la base")
    for pid in sorted(set(por_id_b) - set(por_id_a)):
        problemas.append(f"{pid}: está en la base y no en el archivo")

    for pid in sorted(set(por_id_a) & set(por_id_b)):
        a, b = por_id_a[pid], por_id_b[pid]
        for campo in CAMPOS:
            va, vb = getattr(a, campo), getattr(b, campo)
            if va != vb:
                problemas.append(f"{pid}.{campo}: archivo={va!r} base={vb!r}")

    return problemas


def main() -> int:
    archivo = build_catalog(
        FileCatalogSource(
            POLICIES / "fraud_policies_2025.1.json",
            POLICIES / "policy_bindings_2025.1.json",
        ).fetch()
    )
    base = build_catalog(DbCatalogSource().fetch())

    print(f"archivo : {archivo.version} · {archivo.health}")
    print(f"base    : {base.version} · {base.health}")

    problemas = comparar(archivo, base)

    if problemas:
        print(f"\nFALLA: {len(problemas)} diferencias")
        for p in problemas:
            print(f"  - {p}")
        return 1

    # Las propiedades derivadas no se comparan campo por campo: salen de
    # `condition`, que ya se comparó. Si dos políticas tienen la misma condición
    # y distinto `owner`, el bug está en la derivación y no en la fuente — y eso
    # lo cubren los tests de `test_catalog.py`, sin base.
    print(f"\nOK · {len(archivo.policies)} políticas idénticas en ambas fuentes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
