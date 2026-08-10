"""La API de punta a punta, manejada por completo a través de HTTP.

    uv run python scripts/smoke_api.py

`TestClient` sobre la app real: sin mocks, con Postgres y los proveedores
reales, sin levantar un socket — mismo criterio que el resto de los smokes
del proyecto, que verifican "de punta a punta" contra la base y los
proveedores reales, nunca contra una copia de la app en otro proceso. Lo que
`smoke_decision.py` prueba llamando al grafo directo, esto lo prueba
pasando por la frontera HTTP: ingesta, cola, detalle, resolución si el caso
escala, catálogo y biblioteca de predicados.

Requiere `docker compose up -d` y `seed.py` corrido. `GEMINI_API_KEY` y
`ANTHROPIC_API_KEY` son opcionales, igual que en `smoke_decision.py`.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi.testclient import TestClient
from sqlalchemy import delete

from multiagent_fraud_detection.api.app import app
from multiagent_fraud_detection.db.models import Case, Transaction
from multiagent_fraud_detection.db.session import AsyncSessionLocal

TX_ID = "T-SMOKE-API-CLEAN"

PAYLOAD = {
    "transaction_id": TX_ID,
    "customer_id": "CU-SMOKE-API",
    "amount": "50.00",
    "currency": "PEN",
    "country": "PE",
    "channel": "web",
    "device_id": "D-SMOKE-API",
    "timestamp": "2026-03-10T15:00:00+00:00",
    "merchant_id": "M-SMOKE-API",
}


async def limpiar() -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(delete(Case).where(Case.transaction_id == TX_ID))
            await session.execute(
                delete(Transaction).where(Transaction.transaction_id == TX_ID)
            )


def main() -> int:
    problemas: list[str] = []
    asyncio.run(limpiar())

    with TestClient(app) as client:
        r = client.get("/health")
        if r.status_code != 200:
            problemas.append(f"/health devolvió {r.status_code}")

        r = client.get("/ready")
        if r.status_code != 200:
            problemas.append(f"/ready devolvió {r.status_code}: Postgres no respondió")

        # --- 1. POST /cases: caso nuevo ------------------------------------ #
        r1 = client.post("/api/v1/cases", json=PAYLOAD)
        if r1.status_code != 202:
            problemas.append(f"POST /cases nuevo devolvió {r1.status_code}, se esperaba 202")
        case_id = r1.json()["case_id"]
        print(f"1. POST /cases (nuevo)       -> {r1.status_code}, case_id={case_id}")

        # --- 2. POST /cases: idempotencia ---------------------------------- #
        r2 = client.post("/api/v1/cases", json=PAYLOAD)
        if r2.status_code != 200:
            problemas.append(f"POST /cases repetido devolvió {r2.status_code}, se esperaba 200")
        if r2.json()["case_id"] != case_id:
            problemas.append("POST /cases repetido devolvió un case_id distinto: no es idempotente")
        print(f"2. POST /cases (idempotente) -> {r2.status_code}")

        # --- 3. GET /cases/{id}: el grafo real ya corrió ------------------- #
        # `TestClient` ejecuta los `BackgroundTasks` antes de devolver la
        # respuesta del primer POST, así que para cuando llegamos acá el
        # caso ya pasó por W1 y, si todo salió bien, por W2.
        r3 = client.get(f"/api/v1/cases/{case_id}")
        detalle = r3.json()
        decision = detalle.get("decision")
        print(
            f"3. GET /cases/{{id}}          -> status={detalle['status']}, "
            f"decision={decision['decision'] if decision else None}"
        )
        if detalle["status"] not in ("DECIDED", "PENDING_HUMAN"):
            problemas.append(
                f"el caso quedó en {detalle['status']}, ni DECIDED ni PENDING_HUMAN"
            )

        # --- 4. GET /cases: aparece en la cola ------------------------------ #
        r4 = client.get("/api/v1/cases", params={"limit": 200})
        ids = [item["case_id"] for item in r4.json()["items"]]
        if case_id not in ids:
            problemas.append("el caso no aparece en GET /cases")

        # --- 5. GET /policies, GET /predicates: no vacíos ------------------- #
        r5 = client.get("/api/v1/policies")
        if not r5.json():
            problemas.append("GET /policies devolvió una lista vacía")
        r6 = client.get("/api/v1/predicates")
        if not r6.json():
            problemas.append("GET /predicates devolvió una lista vacía")
        print(f"5. GET /policies, /predicates -> {len(r5.json())} políticas, {len(r6.json())} predicados")

        # --- 6. Si el caso escaló, ejercitar la resolución (W3) ------------- #
        if detalle["status"] == "PENDING_HUMAN":
            r7 = client.post(
                f"/api/v1/cases/{case_id}/resolution",
                json={"action": "APPROVE", "analyst_id": "SMOKE", "notes": "smoke_api"},
            )
            if r7.status_code != 200 or r7.json()["status"] != "RESOLVED":
                problemas.append(f"POST resolution devolvió {r7.status_code}")

            r8 = client.post(
                f"/api/v1/cases/{case_id}/resolution",
                json={"action": "APPROVE", "analyst_id": "SMOKE"},
            )
            if r8.status_code != 409:
                problemas.append(
                    f"la segunda resolution devolvió {r8.status_code}, se esperaba 409"
                )
            print(f"6. POST resolution (W3)      -> {r7.status_code}, luego 409 en la repetida")
        else:
            print("6. (el caso no escaló a PENDING_HUMAN; la resolución no se ejercita en esta corrida)")

    asyncio.run(limpiar())

    print()
    if problemas:
        print(f"FALLA: {len(problemas)} problemas")
        for p in problemas:
            print(f"  - {p}")
        return 1

    print("OK · la API respondió de punta a punta: ingesta, idempotencia, cola,")
    print("     detalle, catálogo de políticas y biblioteca de predicados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
