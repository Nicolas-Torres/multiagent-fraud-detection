"""Exporta la topología del grafo como JSON, para que el panel de detalle del
dashboard la dibuje con React Flow en vez de mantenerla a mano.

Mismo origen que `export_graph_diagram.py` (`build_graph().get_graph()`), and
mismo criterio de no reescribir si no cambió. `__start__`/`__end__` son
marcadores sintéticos de LangGraph, no agentes — se marcan con `synthetic`
para que el frontend decida si los dibuja.

Nodos y aristas se ordenan antes de serializar: `Graph.nodes`/`.edges` no
garantizan un orden estable entre procesos (ver footgun de artefactos no
deterministas), así que el orden de inserción del diccionario no es un
contrato en el que apoyarse.

    uv run python scripts/export_graph_topology.py
"""

import json
from pathlib import Path

from multiagent_fraud_detection.graph.builder import build_graph

JSON_PATH = (
    Path(__file__).resolve().parents[1] / "dashboard" / "src" / "data" / "graph_topology.json"
)


def main() -> None:
    graph = build_graph().get_graph()

    nodos = sorted(
        (
            {"id": id_, "synthetic": id_.startswith("__") and id_.endswith("__")}
            for id_ in graph.nodes
        ),
        key=lambda n: n["id"],
    )
    aristas = sorted(
        (
            {"source": e.source, "target": e.target, "conditional": e.conditional}
            for e in graph.edges
        ),
        key=lambda e: (e["source"], e["target"]),
    )

    salida = json.dumps({"nodes": nodos, "edges": aristas}, indent=2, sort_keys=True)

    if JSON_PATH.exists() and JSON_PATH.read_text(encoding="utf-8").rstrip("\n") == salida:
        print(f"sin cambios: {JSON_PATH.name}")
        return

    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(salida + "\n", encoding="utf-8")
    print(f"escrito: {JSON_PATH.name} ({len(nodos)} nodos, {len(aristas)} aristas)")


if __name__ == "__main__":
    main()
