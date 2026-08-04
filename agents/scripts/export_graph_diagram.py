"""Exporta la topologia del grafo como PNG para el README.

El diagrama se deriva del grafo compilado, no se dibuja a mano. El README lo
referencia por una ruta fija, asi que regenerar el archivo actualiza el README
sin tocarlo.

El PNG lleva fondo blanco horneado, por lo que se lee igual en modo claro y
oscuro de GitHub.

Requiere conexion: `draw_mermaid_png()` no renderiza en local, hace un POST a
la API de mermaid.ink.

    uv run python scripts/export_graph_diagram.py
"""

from pathlib import Path

from src.graph.builder import build_graph

# Independiente del directorio desde el que se ejecute el script.
PNG_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "diagrams" / "graph_topology.png"
)


def main() -> None:
    png = build_graph().get_graph().draw_mermaid_png(background_color="white")

    # Sin este corte, cada corrida deja un blob binario nuevo en git aunque la
    # topologia no haya cambiado.
    if PNG_PATH.exists() and PNG_PATH.read_bytes() == png:
        print(f"sin cambios: {PNG_PATH.name}")
        return

    PNG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PNG_PATH.write_bytes(png)
    print(f"escrito: {PNG_PATH.name} ({len(png):,} bytes)")


if __name__ == "__main__":
    main()