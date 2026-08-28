"""Exporta el spec de OpenAPI de la app real, para que `openapi-typescript`
genere tipos contra la frontera de verdad y no contra un archivo mantenido a
mano.

Mismo criterio que `export_graph_diagram.py`: el artefacto se deriva de la
app, no se escribe. Lo consume `dashboard/package.json` (`generate:api`).

    uv run python scripts/export_openapi.py
"""

import json
from pathlib import Path

from multiagent_fraud_detection.api.app import app

# Independiente del directorio desde el que se ejecute el script.
JSON_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "openapi.json"


def main() -> None:
    spec = json.dumps(app.openapi(), indent=2, sort_keys=True)

    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(spec + "\n", encoding="utf-8")
    print(f"escrito: {JSON_PATH.name} ({len(spec):,} bytes)")


if __name__ == "__main__":
    main()
