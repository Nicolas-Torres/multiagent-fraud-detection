"""Inicialización de observabilidad (LangSmith).

LangGraph/LangChain activan el trazado cuando leen **variables de entorno**
(`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`) — no leen
pydantic-settings. Nuestra configuración vive en `.env` (cargado por
`Settings`), así que este módulo las exporta al proceso al importarse.

Se importa en `src/__init__.py` (o en el entrypoint) para que el trazado esté
activo desde el arranque. Si `LANGSMITH_TRACING` ya está exportado en la shell,
pydantic-settings lo leyó igual y acá se re-exporta el mismo valor.
"""

import logging
import os

from src.config.settings import settings

logger = logging.getLogger(__name__)


def configurar_langsmith() -> None:
    """Exporta la configuración de LangSmith al entorno del proceso."""
    if not settings.langsmith_api_key:
        logger.debug("LangSmith sin API key: trazado desactivado")
        return

    os.environ.setdefault("LANGSMITH_TRACING", "true" if settings.langsmith_tracing else "false")
    os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    logger.info(
        "LangSmith: trazado=%s proyecto=%s",
        os.environ["LANGSMITH_TRACING"],
        os.environ["LANGSMITH_PROJECT"],
    )


configurar_langsmith()
