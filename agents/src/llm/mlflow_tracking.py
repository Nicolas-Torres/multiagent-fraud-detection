"""Registro de experimentos en MLflow (D9).

El harness registra cada corrida en MLflow con el tracking URI de
`MLFLOW_TRACKING_URI` (servidor remoto propio, `https://mlflow.chris-co.net`,
sin autenticación). No hay base local de MLflow ni Alembic que la toque.

El grafo de agentes NO depende de MLflow: el tracking vive en el harness.

Uso desde el harness:

    with mlflow_run("deterministic", params={...}) as run:
        run.log_metric("f1_decision", 0.95)
"""

import logging
from contextlib import contextmanager
from typing import Iterator

from src.config.settings import settings

logger = logging.getLogger(__name__)


class MlfRun:
    """Wrapper fino sobre el run activo de MLflow."""

    def __init__(self, mlflow, run) -> None:
        self._mlflow = mlflow
        self._run = run

    def log_metric(self, nombre: str, valor: float) -> None:
        self._mlflow.log_metric(nombre, valor)


def _tracking_uri() -> str | None:
    return settings.mlflow_tracking_uri or None


@contextmanager
def mlflow_run(nombre: str, params: dict) -> Iterator[MlfRun | None]:
    """Abre un run de MLflow si está configurado; si no, un no-op.

    Si `MLFLOW_TRACKING_URI` no está seteado, el contexto no registra nada pero
    no rompe la corrida (el harness funciona igual sin experimentos).
    """
    uri = _tracking_uri()
    if not uri:
        logger.info("MLflow sin tracking URI: corrida no registrada")
        yield None
        return

    import mlflow

    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("fraud_evaluation")
    with mlflow.start_run(run_name=nombre) as run:
        for clave, valor in params.items():
            mlflow.log_param(clave, valor)
        # Tags de entorno (D9): dev vs despliegue, para separar corridas.
        mlflow.set_tag("entorno", settings.llm_provider)
        mlflow.set_tag("threat_intel_offline", settings.threat_intel_offline)
        yield MlfRun(mlflow, run)
