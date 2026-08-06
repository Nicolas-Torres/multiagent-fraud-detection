"""Enforcement del allowlist: qué fuente puede entrar al corpus.

Se aplica en el **camino de escritura** (ADR-0014): lo que no pasa por acá no
llega a `threat_indicators`, así que en runtime no hay nada que filtrar.

## Por qué existe si el proveedor ya filtra

La API acepta `allowed_domains` y descarta resultados de fuera de la lista. Eso
es **optimización de costo**, no gobernanza: reduce lo que se paga y lo que
viaja, pero la garantía la tiene que dar código nuestro, sobre lo que efectivamente
volvió. Delegar la única barrera a un tercero deja la auditoría sin sujeto.

Todo acá es función pura: sin red, sin base, sin reloj. Es el módulo de la etapa
con mejor relación cobertura/esfuerzo.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class Rejected:
    url: str  # `str` y no una URL parseada: una fuente rechazada puede venir malformada
    reason: str


def normalize_allowlist(domains: Iterable[str]) -> frozenset[str]:
    """Dominios pelados, en minúscula, sin punto final ni esquema.

    Es también el formato que la API exige en `allowed_domains`, así que la misma
    lista normalizada sirve para las dos cosas y no pueden divergir.
    """
    limpio = set()
    for d in domains:
        d = d.strip().lower().rstrip(".")
        if d:
            limpio.add(d)
    return frozenset(limpio)


def _host(url: str) -> str | None:
    """El host real de la URL, o `None` si no se puede determinar.

    Se usa `urlsplit(...).hostname` y **no** `netloc`: `netloc` incluye el
    userinfo, así que `https://banco.com@evil.com/x` lo mostraría empezando por
    `banco.com`. `hostname` devuelve `evil.com`, que es a dónde va el navegador.
    Es el ataque clásico contra un allowlist y se neutraliza eligiendo bien el
    atributo.
    """
    try:
        partes = urlsplit(url)
    except ValueError:
        return None

    if partes.scheme != "https":
        return None

    host = (partes.hostname or "").lower().rstrip(".")
    if not host:
        return None

    # IDNA: `bаnco.com` con una `а` cirílica es un host distinto que se dibuja
    # igual. Codificar a punycode lo vuelve visible —y falla si el host tiene
    # caracteres que no forman un dominio válido—.
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return None

    
def is_allowed(url: str, allowlist: frozenset[str]) -> bool:
    """El host está en la lista, o es subdominio de alguno de sus miembros.

    Los subdominios entran a propósito: es lo que hace el proveedor con
    `allowed_domains`, y si acá no lo hiciéramos las dos listas rechazarían cosas
    distintas con la misma configuración.
    """
    host = _host(url)
    if host is None:
        return False
    return any(host == d or host.endswith(f".{d}") for d in allowlist)


def enforce(
    urls: Sequence[str], allowlist: frozenset[str]
) -> tuple[tuple[str, ...], tuple[Rejected, ...]]:
    """Parte las fuentes en aceptadas y rechazadas, con motivo.

    Lo rechazado no se descarta en silencio: va al informe del script, que es el
    audit trail de que el allowlist hizo algo.
    """
    aceptadas: list[str] = []
    rechazadas: list[Rejected] = []

    for url in urls:
        host = _host(url)
        if host is None:
            rechazadas.append(Rejected(url, "url invalida, no https o host ilegible"))
        elif not is_allowed(url, allowlist):
            rechazadas.append(Rejected(url, f"dominio {host} fuera del allowlist"))
        else:
            aceptadas.append(url)

    return tuple(aceptadas), tuple(rechazadas)
