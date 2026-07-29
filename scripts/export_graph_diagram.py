"""Exporta la topologia del grafo como diagrama Mermaid.

El diagrama se deriva del grafo compilado, no se dibuja a mano: no puede
desincronizarse del codigo. Muestra nodos y aristas; la agrupacion en
supersteps no es visible aqui y la afirma `scripts/smoke_graph.py`.

    uv run python scripts/export_graph_diagram.py                  # a stdout
    uv run python scripts/export_graph_diagram.py docs/diagramas/graph.mmd
"""

from pathlib import Path

from multiagent_fraud_detection.graph.builder import build_graph

GRAPH_MMD_PATH = "docs/diagram/graph.png"

def main() -> None:
    destino = Path(GRAPH_MMD_PATH)
    destino.parent.mkdir(parents=True, exist_ok=True)

    mermaid_png = build_graph().get_graph().draw_mermaid_png()

    with open(destino, "wb") as f:
        f.write(mermaid_png)

    print(f"escrito: {destino} ({len(mermaid_png.splitlines())} lineas)")

if __name__ == "__main__":
    main()
