"""Adaptador del dataset en CSV al dominio.

Un adaptador por fuente: acá vive toda la normalización de formato —`"08-20"` →
`(8, 20)`, `"PE;ES"` → `["PE", "ES"]`, `chanel` → `channel`— y de acá sale el
dato canónico. El dominio y los schemas no saben que existe un CSV.

Vive en `scripts/` y **no importa nada de `db/`** a propósito: lo consumen tanto
`seed.py`, que sí necesita base, como `check_policies.py`, que corre en CI sin
Postgres levantado. Si importara la sesión, el gate de CI arrastraría un servicio
que no usa.
"""

import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from multiagent_fraud_detection.schemas.customer_behavior import CustomerBehaviorIn
from multiagent_fraud_detection.schemas.merchant_blacklist import MerchantBlacklistIn
from multiagent_fraud_detection.schemas.transaction import TransactionIn
from multiagent_fraud_detection.schemas.web_search_allowlist import (
    WebSearchAllowlistIn,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _lista(celda: str) -> list[str]:
    """`"PE;ES"` → `["PE", "ES"]`; `""` → `[]`.

    Una celda vacía es una **lista vacía**, no un dato faltante: "ningún
    dispositivo habitual" significa que todo dispositivo es nuevo. Eso es señal,
    y el contrato lo declara válido explícitamente.
    """
    return [x for x in celda.split(";") if x]


def leer_perfiles() -> list[CustomerBehaviorIn]:
    ruta = DATA_DIR / "customer_behaviors.csv"
    perfiles = []

    with ruta.open(encoding="utf-8", newline="") as fh:
        for fila in csv.DictReader(fh):
            inicio, fin = fila["usual_hours"].split("-")

            # `last_profile_update` viene **naive en hora local del cliente** y
            # la columna es TIMESTAMPTZ. Es la única normalización que necesita
            # otra columna del mismo registro: sin la zona, un perfil de Lima
            # quedaría cinco horas corrido y FP-09 evaluaría otra ventana.
            zona = ZoneInfo(fila["timezone"])
            actualizado = datetime.fromisoformat(
                fila["last_profile_update"]
            ).replace(tzinfo=zona)

            perfiles.append(
                CustomerBehaviorIn(
                    customer_id=fila["customer_id"],
                    usual_amount_avg=Decimal(fila["usual_amount_avg"]),
                    usual_hour_start=int(inicio),
                    usual_hour_end=int(fin),
                    usual_countries=_lista(fila["usual_countries"]),
                    usual_devices=_lista(fila["usual_devices"]),
                    usual_channel=fila["usual_channel"],
                    account_creation_date=date.fromisoformat(
                        fila["account_creation_date"]
                    ),
                    last_profile_update=actualizado,
                    daily_limit=Decimal(fila["daily_limit"]),
                    currency=fila["currency"],
                    timezone=fila["timezone"],
                    segment=fila["segment"],
                )
            )

    return perfiles


def leer_transacciones() -> list[TransactionIn]:
    ruta = DATA_DIR / "transactions.csv"

    with ruta.open(encoding="utf-8", newline="") as fh:
        return [
            TransactionIn(
                transaction_id=fila["transaction_id"],
                customer_id=fila["customer_id"],
                amount=Decimal(fila["amount"]),
                currency=fila["currency"],
                country=fila["country"],
                # `chanel` → `channel`. El typo viene del enunciado del reto, no
                # del generador. Renombrar una columna es traducción de forma
                # pura: o el mapeo existe o revienta ruidosamente. Corregirlo en
                # la fuente habría escondido que el adaptador hace su trabajo.
                channel=fila["chanel"],
                device_id=fila["device_id"],
                # Ya trae offset explícito (`+00:00`), a diferencia del perfil.
                timestamp=datetime.fromisoformat(fila["timestamp"]),
                merchant_id=fila["merchant_id"],
                issuer_bank=fila["issuer_bank"] or None,
            )
            for fila in csv.DictReader(fh)
        ]


def leer_ground_truth() -> dict[str, dict]:
    """`transaction_id` → etiquetas esperadas.

    Sólo lo lee el harness: el sistema **nunca** ve este archivo.
    """
    ruta = DATA_DIR / "ground_truth.csv"

    with ruta.open(encoding="utf-8", newline="") as fh:
        return {
            fila["transaction_id"]: {
                "policies": sorted(_lista(fila["expected_policies"])),
                "decision": fila["expected_decision"],
                "is_closing": fila["is_closing"] == "true",
            }
            for fila in csv.DictReader(fh)
        }


# Dato de gobernanza, no del dataset... salvo que en este caso sí lo es: el
# generador eligió `M-999` como el comercio marcado, y las etiquetas de FP-07
# dependen de que esta fila exista. Va acá y no en una migración porque las
# migraciones son esquema.
BLACKLIST = [
    MerchantBlacklistIn(
        merchant_id="M-999",
        reason="Comercio con reportes recurrentes de fraude (dataset sintético)",
        added_by="seed",
    )
]

# Supervisores y asociaciones bancarias, no blogs: son las fuentes cuya
# publicación sobre un emisor es un hecho verificable, no una opinión.
ALLOWLIST = [
    WebSearchAllowlistIn(
        domain="sbs.gob.pe",
        reason=(
            "Superintendencia de Banca, Seguros y AFP del Perú: regulador "
            "bancario nacional, fuente primaria de alertas sobre entidades "
            "supervisadas."
        ),
        added_by="seed",
    ),
    WebSearchAllowlistIn(
        domain="asbanc.com.pe",
        reason=(
            "Asociación de Bancos del Perú: gremio bancario, publica alertas "
            "de phishing y campañas de fraude dirigidas a clientes de sus "
            "asociados."
        ),
        added_by="seed",
    ),
]
