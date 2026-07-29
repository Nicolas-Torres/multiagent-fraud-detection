"""Inyecta la topologia del grafo en el README como bloque Mermaid.

Muestra nodos y aristas; la agrupacion en supersteps no es visible aqui y la
afirma `scripts/smoke_graph.py`.

    uv run python scripts/sync_graph_diagram.py           # regenera
    uv run python scripts/sync_graph_diagram.py --check   # falla si esta desactualizado

El README debe contener, una sola vez, estas dos marcas:

    <!-- graph-topology:start -->
    <!-- graph-topology:end -->
"""

import sys
from pathlib import Path

from multiagent_fraud_detection.graph.builder import build_graph

README = Path("README.md")
INICIO = "<!-- graph-topology:start -->"
FIN = "<!-- graph-topology:end -->"

mermaid_config = {
    "config": {
        "theme": "neutral"
    }
}

def bloque_mermaid() -> str:
    diagrama = build_graph().get_graph().draw_mermaid(frontmatter_config=mermaid_config).strip()
    return f"{INICIO}\n\n```mermaid\n{diagrama}\n```\n\n{FIN}"


def con_diagrama(texto: str, bloque: str) -> str:
    inicio, fin = texto.find(INICIO), texto.find(FIN)
    if inicio == -1 or fin == -1 or fin < inicio:
        raise SystemExit(
            f"{README.name} no tiene las marcas del diagrama.\n"
            f"Agrega estas dos lineas donde quieras que aparezca:\n"
            f"  {INICIO}\n  {FIN}"
        )
    return texto[:inicio] + bloque + texto[fin + len(FIN) :]


def main() -> None:
    actual = README.read_text(encoding="utf-8")
    nuevo = con_diagrama(actual, bloque_mermaid())

    if "--check" in sys.argv:
        if actual != nuevo:
            raise SystemExit(
                "El diagrama del README esta desactualizado.\n"
                "Corre: uv run python scripts/sync_graph_diagram.py"
            )
        print("README.md: diagrama al dia")
        return

    if actual == nuevo:
        print("README.md: sin cambios")
        return

    README.write_text(nuevo, encoding="utf-8")
    print(f"README.md: diagrama actualizado ({len(nuevo.splitlines())} lineas)")


if __name__ == "__main__":
    main()
