"""Trazas (HTTP + DB) y logs correlacionados, vía OTLP a un collector (Alloy,
ADR-0024). Mismo criterio que `propagar_langsmith` en `settings.py` —una
función chica, junto a la config, en vez de cargar `api/app.py` con el
cableado de un proveedor de observabilidad— pero separada de `settings.py`
en su propio archivo para no cargar ese módulo (importado por todo entry
point) con las dependencias de OpenTelemetry.
"""

import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.db.session import engine


def instrumentar_observabilidad(app: FastAPI) -> None:
    """Sin `otel_exporter_otlp_endpoint` no se toca nada — ni `pytest` ni un
    entorno sin el stack local levantado intentan abrir una conexión de red
    al arrancar."""
    if not settings.otel_exporter_otlp_endpoint:
        return

    resource = Resource.create({"service.name": settings.otel_service_name})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
        )
    )
    trace.set_tracer_provider(tracer_provider)

    # El `LoggingHandler` inyecta trace_id/span_id en cada log emitido
    # dentro de un request — es lo que permite saltar de una traza en Tempo
    # a sus logs exactos en Loki. Se agrega al logger raíz, además del
    # handler de consola que ya existe: no reemplaza nada.
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
        )
    )
    logging.getLogger().addHandler(LoggingHandler(logger_provider=logger_provider))

    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
    # `engine.sync_engine`: la instrumentación engancha eventos DBAPI, que
    # viven en el motor síncrono interno incluso cuando el engine público es
    # async (`create_async_engine`).
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine, tracer_provider=tracer_provider)
