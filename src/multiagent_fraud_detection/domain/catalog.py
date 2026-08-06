"""Carga y validación del catálogo de políticas.

Junta dos artefactos con dueños distintos —el documento normativo del banco y la
vinculación que escribimos nosotros (ADR-0007)— y produce objetos con `owner`,
`requires` y `state` **derivados**, nunca escritos.

## Por qué este módulo existe

Con las reglas como dato, la validación se corre de tiempo de compilación a
tiempo de carga. Antes, una regla mal escrita no compilaba; ahora es una fila que
nadie compiló. Esto es lo que la reemplaza, y por eso las validaciones se juntan
**todas** antes de fallar: quien corrige un catálogo quiere la lista completa de
problemas, no el primero.

## Qué es error y qué es estado

| Situación | Qué pasa |
|---|---|
| predicado inexistente, parámetro fuera de rango, acción inválida | **error** — no se carga |
| la huella dejó de coincidir | **estado** `STALE` — se degrada |
| documento sin vinculación | **estado** `PENDING` |
| vinculación sin condición y con motivo | **estado** `EXCLUDED` |

La distinción es deliberada. Un catálogo mal formado es culpa nuestra y tiene que
frenar el arranque. Que el banco edite un texto no puede dejar el motor fuera de
servicio: la política se degrada —deja de evaluarse, sigue siendo citable— igual
que un agente que falla degrada la decisión en vez de abortarla.

## El puerto de origen

La carga está partida en dos por la fase 3 de ADR-0007, que muda el catálogo de
archivos versionados a tablas:

- **`CatalogSource`** trae los registros **crudos**, con la forma exacta en que el
  banco entrega el catálogo. Hay dos implementaciones: `FileCatalogSource` acá, y
  `DbCatalogSource` en `db/repositories/`.
- **`build_catalog`** valida y deriva. Es **una sola** implementación, compartida
  por las dos fuentes.

El corte va ahí y no después a propósito. Si el puerto devolviera `Policy` ya
construidas, cada fuente tendría que reimplementar los cuatro estados y los
cuatro derivados, y el test que afirma que ambas producen el mismo `PolicyCatalog`
estaría comparando dos copias del mismo bug.

Que lo crudo sean `dict` y no un tercer schema tipado también es deliberado: esa
forma **es** el formato de entrega, y las columnas de las tablas la espejan una a
una. Tipar un intermedio que se consume dos líneas después sería una tercera
fuente de verdad para la misma forma.

**El puerto es síncrono.** El catálogo se lee una vez por proceso, no por caso, y
`GraphContext.catalog` lo toma desde un `default_factory`, que no puede esperar
una corrutina. `DbCatalogSource` usa engine síncrono por el mismo motivo por el
que lo usa `migrations/env.py`: psycopg3 da sync y async con la misma URL, y el
async se paga solo donde hay concurrencia real.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from multiagent_fraud_detection.domain.predicates import (
    CONTEXT_INPUTS,
    INTEL_INPUTS,
    LIBRARY,
    Input,
    Predicate,
)
from multiagent_fraud_detection.enums import DecisionType


class CatalogError(Exception):
    """El catálogo no se puede cargar. Trae la lista completa de problemas."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        cuerpo = "\n".join(f"  - {p}" for p in problems)
        super().__init__(f"catálogo inválido ({len(problems)} problemas):\n{cuerpo}")


class PolicyState(StrEnum):
    ACTIVE = "active"      # vinculada, huella vigente → el motor la evalúa
    EXCLUDED = "excluded"  # sin condición, con motivo registrado
    PENDING = "pending"    # documento sin vinculación
    STALE = "stale"        # el texto cambió después de traducirla


class Owner(StrEnum):
    CONTEXT = "context"
    BEHAVIORAL = "behavioral"
    THREAT_INTEL = "threat_intel"


def owner_of(requires: frozenset[Input]) -> Owner:
    """Qué agente evalúa una condición, derivado de sus insumos. Tres ramas.

    `indicators` **gana** sobre la partición contexto/comportamiento (ADR-0015):
    `issuer_under_alert` pide `transaction` e `indicators`, y sin la precedencia
    la partición binaria lo mandaría a Behavioral. El motivo es de honestidad de
    datos, no de estética — `WorkingSignal.emitted_by` es lo que el harness usa
    para atribuir falsos positivos, y ahí no puede mentir.
    """
    if requires & INTEL_INPUTS:
        return Owner.THREAT_INTEL
    return Owner.CONTEXT if requires <= CONTEXT_INPUTS else Owner.BEHAVIORAL


@dataclass(frozen=True, slots=True)
class Step:
    """Un predicado con sus parámetros, tal como lo invoca el intérprete."""

    predicate: Predicate
    params: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Policy:
    """La vista unificada: documento + vinculación + lo derivado."""

    policy_id: str
    version: str
    text: str
    state: PolicyState
    action: DecisionType | None = None
    condition: tuple[Step, ...] = ()
    excluded_reason: str | None = None
    bound_by: str | None = None

    @property
    def evaluable(self) -> bool:
        return self.state is PolicyState.ACTIVE

    @property
    def requires(self) -> frozenset[Input]:
        return frozenset().union(*(s.predicate.requires for s in self.condition)) if self.condition else frozenset()

    @property
    def owner(self) -> Owner | None:
        if not self.condition:
            return None
        return owner_of(self.requires)

    @property
    def signals(self) -> tuple[str, ...]:
        return tuple(s.predicate.signal_code(**s.params) for s in self.condition)


@dataclass(frozen=True, slots=True)
class PolicyCatalog:
    version: str
    reference_currency: str
    policies: tuple[Policy, ...]

    def __getitem__(self, policy_id: str) -> Policy:
        return next(p for p in self.policies if p.policy_id == policy_id)

    def evaluable_by(self, owner: Owner) -> tuple[Policy, ...]:
        """Las políticas que un agente tiene que evaluar. Ordenadas por id.

        El orden es parte del contrato con el harness: dos corridas idénticas
        tienen que producir las señales en el mismo orden, o el diff es ruido.
        """
        return tuple(
            sorted(
                (p for p in self.policies if p.evaluable and p.owner is owner),
                key=lambda p: p.policy_id,
            )
        )

    def by_state(self, state: PolicyState) -> tuple[Policy, ...]:
        return tuple(p for p in self.policies if p.state is state)

    @property
    def health(self) -> dict[str, int]:
        """Las dos métricas operativas del entregable 6, más el resto."""
        return {s.value: len(self.by_state(s)) for s in PolicyState}


# --------------------------------------------------------------------------- #
# El puerto de origen
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RawCatalog:
    """Los registros crudos, antes de validar y derivar.

    Espeja el formato de entrega: `documents` es el arreglo del JSON normativo,
    `header` son los metadatos del sobre de vinculación y `bindings` su lista.
    Las tablas de la fase 3 tienen la misma partición —`fraud_policies`,
    `binding_sets`, `policy_bindings`—, así que reconstruir esta forma desde
    Postgres es una proyección, no una traducción.
    """

    documents: list[dict[str, Any]]
    header: dict[str, Any]
    bindings: list[dict[str, Any]]


class CatalogSource(Protocol):
    """De dónde salen los registros crudos.

    Deliberadamente mínimo: una sola operación, sin parámetros. Quién es el
    catálogo vigente lo decide la construcción de la fuente, no el llamador.
    """

    def fetch(self) -> RawCatalog: ...


@dataclass(frozen=True, slots=True)
class FileCatalogSource:
    """Los dos JSON versionados en `data/policies/`. Fase 2 de ADR-0007.

    Es la fuente del gate offline: `check_policies.py` corre en CI sin Postgres
    levantado, y ese gate deja de existir el día que la única fuente sea la base.
    """

    documents_path: Path
    bindings_path: Path

    def fetch(self) -> RawCatalog:
        documentos = json.loads(self.documents_path.read_text(encoding="utf-8"))
        sobre = json.loads(self.bindings_path.read_text(encoding="utf-8"))

        header = {k: v for k, v in sobre.items() if k != "bindings"}
        return RawCatalog(
            documents=documentos,
            header=header,
            bindings=sobre["bindings"],
        )


# --------------------------------------------------------------------------- #
# Validación y derivación
# --------------------------------------------------------------------------- #


def fingerprint(text: str, *, algorithm: str = "sha256") -> str:
    """Huella del texto normativo.

    Se hashea **sólo el texto**, no el objeto entero: si el banco corrige un typo
    en un campo de metadatos sin tocar la norma, la traducción sigue siendo
    válida y no tiene por qué invalidarse.
    """
    digest = hashlib.new(algorithm, text.encode("utf-8")).hexdigest()
    return f"{algorithm}:{digest}"


def build_catalog(raw: RawCatalog) -> PolicyCatalog:
    """Valida los registros crudos y deriva la vista unificada.

    Una sola implementación para todas las fuentes. Es lo que hace que el test
    "archivo y base producen el mismo catálogo" pruebe algo sobre los **datos** y
    no sobre dos copias de la misma lógica.
    """
    documentos = raw.documents
    sobre = raw.header

    algoritmo = sobre.get("fingerprint_algorithm", "sha256")
    campo = sobre.get("fingerprint_field", "rule")
    problems: list[str] = []

    por_id = {d["policy_id"]: d for d in documentos}
    if len(por_id) != len(documentos):
        problems.append("hay `policy_id` duplicados en el catálogo de documentos")

    vinculaciones: dict[str, dict] = {}
    for v in raw.bindings:
        pid = v["policy_id"]
        if pid in vinculaciones:
            problems.append(f"{pid}: vinculación duplicada")
        vinculaciones[pid] = v
        if pid not in por_id:
            problems.append(f"{pid}: vinculación sin documento correspondiente")

    politicas: list[Policy] = []

    for pid, doc in por_id.items():
        texto = doc[campo]
        v = vinculaciones.get(pid)

        if v is None:
            politicas.append(
                Policy(pid, doc["version"], texto, PolicyState.PENDING)
            )
            continue

        # --- acción --------------------------------------------------------
        accion = None
        try:
            accion = DecisionType(v["action"])
            if accion is DecisionType.APPROVE:
                problems.append(f"{pid}: `action` no puede ser APPROVE")
        except ValueError:
            problems.append(f"{pid}: acción desconocida {v['action']!r}")

        # --- condición -----------------------------------------------------
        cruda = v.get("condition")
        pasos: list[Step] = []

        if cruda is None:
            if not v.get("excluded_reason"):
                problems.append(
                    f"{pid}: `condition: null` exige `excluded_reason`"
                )
        else:
            if not cruda:
                problems.append(f"{pid}: `condition` vacía; usá `null` con motivo")
            for paso in cruda:
                nombre = paso["predicate"]
                pred = LIBRARY.get(nombre)
                if pred is None:
                    problems.append(f"{pid}: predicado desconocido {nombre!r}")
                    continue
                params = paso.get("params", {})
                sobrantes = set(params) - set(pred.params)
                faltantes = set(pred.params) - set(params)
                if sobrantes:
                    problems.append(f"{pid}/{nombre}: parámetros de más {sorted(sobrantes)}")
                if faltantes:
                    problems.append(f"{pid}/{nombre}: faltan parámetros {sorted(faltantes)}")
                for k, spec in pred.params.items():
                    if k in params:
                        try:
                            spec.validate(f"{pid}/{nombre}.{k}", params[k])
                        except ValueError as e:
                            problems.append(str(e))
                pasos.append(Step(pred, params))

            # --- ninguna política abarca los dos nodos ---------------------
            if pasos and len({s.predicate.is_context() for s in pasos}) > 1:
                problems.append(
                    f"{pid}: la condición abarca Context y Behavioral; ningún "
                    f"nodo puede evaluarla completa"
                )

        # --- estado --------------------------------------------------------
        if cruda is None:
            estado = PolicyState.EXCLUDED
        elif not v.get("active", True):
            estado = PolicyState.EXCLUDED
        elif v.get("source_fingerprint") != fingerprint(texto, algorithm=algoritmo):
            estado = PolicyState.STALE
        else:
            estado = PolicyState.ACTIVE

        politicas.append(
            Policy(
                policy_id=pid,
                version=doc["version"],
                text=texto,
                state=estado,
                action=accion,
                condition=tuple(pasos),
                excluded_reason=v.get("excluded_reason"),
                bound_by=v.get("bound_by"),
            )
        )

    if problems:
        raise CatalogError(problems)

    return PolicyCatalog(
        version=sobre["binding_set_version"],
        reference_currency=sobre.get("reference_currency", "USD"),
        policies=tuple(sorted(politicas, key=lambda p: p.policy_id)),
    )


def load_catalog(documents_path: Path, bindings_path: Path) -> PolicyCatalog:
    """Atajo para la fuente de archivos.

    Existe porque es la firma que ya usan `check_policies.py`, `GraphContext` y
    catorce casos de `test_catalog.py`. Extraer el puerto no tiene por qué
    hacerles pagar nada.
    """
    return build_catalog(FileCatalogSource(documents_path, bindings_path).fetch())


# --------------------------------------------------------------------------- #
# La biblioteca como dato (para el compositor del dashboard)
# --------------------------------------------------------------------------- #


def predicate_library_spec() -> list[dict[str, Any]]:
    """Los quince predicados en forma serializable.

    Alimenta `GET /api/v1/predicates`. Si esta lista viviera en el frontend
    habría dos fuentes de verdad para lo mismo, y la segunda se desactualizaría
    en silencio el día que se agregue un predicado.
    """
    return [
        {
            "name": p.name,
            "description": p.description,
            "requires": sorted(p.requires),
            "severity": p.severity.value,
            "owner": owner_of(p.requires),
            "params": {
                k: {
                    "kind": s.kind,
                    "label": s.label,
                    "minimum": s.minimum,
                    "maximum": s.maximum,
                    "choices": list(s.choices),
                }
                for k, s in p.params.items()
            },
        }
        for p in LIBRARY.values()
    ]
