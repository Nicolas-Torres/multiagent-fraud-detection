"""Indexa el catálogo de políticas en `policy_chunks` (D8).

    uv run python scripts/index_policies.py

Lee `data/policies/fraud_policies_2025.1.json`, genera un chunk por política
con su embedding (Gemini) y lo carga con upsert. Reintento sustituye, no
acumula (misma semántica que el seed).

El chunk se construye para que la recuperación semántica encuentre la política
desde las señales: texto de la regla + descriptor de la transacción que la
activa. `metadata` guarda `action` y `severity` sugeridas para el RAG.
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.db.session import AsyncSessionLocal
from src.db.models import PolicyChunk
from src.llm.providers import build_embeddings

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CATALOGO = DATA_DIR / "policies" / "fraud_policies_2025.1.json"

# Acción prescrita y severidad sugerida por política, para `metadata`.
# No decide el veredicto: solo enriquece el chunk para el RAG y la cita.
POLICY_ACTION = {
    "FP-01": "CHALLENGE", "FP-02": "ESCALATE_TO_HUMAN", "FP-03": "BLOCK",
    "FP-04": "BLOCK", "FP-05": "ESCALATE_TO_HUMAN", "FP-06": "CHALLENGE",
    "FP-07": "ESCALATE_TO_HUMAN", "FP-08": "ESCALATE_TO_HUMAN",
    "FP-09": "BLOCK", "FP-11": "BLOCK",
}
POLICY_SEVERITY = {
    "FP-01": "medium", "FP-02": "high", "FP-03": "high", "FP-04": "high",
    "FP-05": "high", "FP-06": "medium", "FP-07": "high", "FP-08": "high",
    "FP-09": "high", "FP-11": "high",
}


def _chunk_text(policy: dict) -> str:
    return (
        f"Política {policy['policy_id']} (versión {policy['version']}): "
        f"{policy['rule']}"
    )


async def indexar() -> None:
    catalogo = json.loads(CATALOGO.read_text(encoding="utf-8"))
    embeddings = build_embeddings()

    print(f"Indexando {len(catalogo)} políticas con "
          f"{embeddings.__class__.__name__}...")

    # Un lote: el catálogo es chico (11 políticas). `embed_documents` de una.
    textos = [_chunk_text(p) for p in catalogo]
    vectores = await embeddings.aembed_documents(textos)

    filas = []
    for politica, vector in zip(catalogo, vectores):
        policy_id = politica["policy_id"]
        chunk_id = hashlib.sha1(
            f"{policy_id}:{politica['version']}".encode()
        ).hexdigest()[:16]
        filas.append({
            "chunk_id": chunk_id,
            "policy_id": policy_id,
            "version": politica["version"],
            "content": _chunk_text(politica),
            "embedding": vector,
            "chunk_metadata": {
                "action": POLICY_ACTION.get(policy_id),
                "severity": POLICY_SEVERITY.get(policy_id),
            },
        })

    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = pg_insert(PolicyChunk).values(filas)
            stmt = stmt.on_conflict_do_update(
                index_elements=["chunk_id"],
                set_={
                    "content": stmt.excluded["content"],
                    "embedding": stmt.excluded["embedding"],
                    "metadata": stmt.excluded["metadata"],
                    "version": stmt.excluded["version"],
                },
            )
            await session.execute(stmt)

    print(f"  {len(filas)} chunks en policy_chunks (upsert)")


async def main() -> int:
    if not CATALOGO.exists():
        print(f"FALTA {CATALOGO}")
        return 1
    await indexar()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
