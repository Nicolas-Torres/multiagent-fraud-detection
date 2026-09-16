"""Renderiza a PNG los diagramas Mermaid hand-drawn de docs/diagrams/.

    uv run python scripts/export_c4_diagrams.py
    uv run python scripts/export_c4_diagrams.py --check   # gate, sin red

A diferencia de `export_data_model_diagram.py`, el `.mmd` fuente de estos
diagramas no se deriva de nada en el código -es contenido curado a mano-,
así que `--check` sólo confirma que el PNG está al día respecto de su
propio `.mmd`, no que el `.mmd` refleje el sistema real. Eso lo sigue
revisando una persona al cerrar cada etapa.

`ciclo-de-vida` vive en dos notaciones a propósito (docs/adr, comparación
LikeC4 vs. Mermaid): la fuente en LikeC4 (`docs/diagrams/likec4/*.c4`,
vista dinámica, se renderiza con `likec4 export png`) y esta, en Mermaid
—salida `ciclo-de-vida-mermaid.png`, para no pisar la de LikeC4—. Cada
una responde una pregunta distinta según el mismo criterio: estructura
en LikeC4, comportamiento en runtime acá.

Mismo renderer que `export_data_model_diagram.py`: `draw_mermaid_png`
(vía mermaid.ink) — nada nuevo que instalar.
"""

import hashlib
import sys
from pathlib import Path

DIAGRAMS = Path(__file__).resolve().parents[1] / "docs" / "diagrams"

# (fuente .mmd sin extensión, salida .png sin extensión) — divergen porque
# ciclo-de-vida-mermaid.png convive con ciclo-de-vida-likec4.png.
DIAGRAMAS = [("ciclo-de-vida", "ciclo-de-vida-mermaid")]


def _hash_actual(png_path: Path) -> str | None:
    if not png_path.exists():
        return None
    return hashlib.sha256(png_path.read_bytes()).hexdigest()


def main() -> int:
    check = "--check" in sys.argv
    exit_code = 0

    for fuente, salida in DIAGRAMAS:
        mmd_path = DIAGRAMS / f"{fuente}.mmd"
        png_path = DIAGRAMS / f"{salida}.png"

        if not mmd_path.exists():
            print(f"falta: {mmd_path.name}", file=sys.stderr)
            exit_code = 1
            continue

        mermaid = mmd_path.read_text(encoding="utf-8")

        if check:
            # --check no debe pegarle a la red: sólo confirma que el PNG
            # exista y sea más nuevo que el .mmd que lo origina.
            if not png_path.exists() or png_path.stat().st_mtime < mmd_path.stat().st_mtime:
                print(f"desactualizado: {png_path.name} (regenerar sin --check)", file=sys.stderr)
                exit_code = 1
            else:
                print(f"al día: {png_path.name}")
            continue

        from langchain_core.runnables.graph_mermaid import draw_mermaid_png

        antes = _hash_actual(png_path)
        png = draw_mermaid_png(mermaid_syntax=mermaid, background_color="white", max_retries=3, retry_delay=2.0)
        png_path.write_bytes(png)
        despues = hashlib.sha256(png).hexdigest()

        if antes == despues:
            print(f"sin cambios: {png_path.name}")
        else:
            print(f"escrito: {png_path.name} ({len(png):,} bytes)")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
