# Nombre de archivo: metrics.py
# Ubicación de archivo: nlp_intent/app/metrics.py
# Descripción: Exposición de métricas Prometheus para nlp_intent

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    CONTENT_TYPE_LATEST,
    generate_latest,
)

REGISTRY = CollectorRegistry()

REQUEST_COUNT = Counter(
    "nlp_intent_requests_total",
    "Total de solicitudes de clasificación procesadas",
    registry=REGISTRY,
)
REQUEST_LATENCY = Histogram(
    "nlp_intent_request_latency_seconds",
    "Latencia de las solicitudes de clasificación en segundos",
    registry=REGISTRY,
)


def record_request(latency: float) -> None:
    """Registra una solicitud y su latencia."""
    REQUEST_COUNT.inc()
    REQUEST_LATENCY.observe(latency)


def export_metrics() -> bytes:
    """Devuelve las métricas en formato Prometheus."""
    return generate_latest(REGISTRY)


def reset_metrics() -> None:
    """Restablece los contadores; se usa solo en las pruebas."""
    global REQUEST_COUNT, REQUEST_LATENCY
    REGISTRY.unregister(REQUEST_COUNT)
    REGISTRY.unregister(REQUEST_LATENCY)
    REQUEST_COUNT = Counter(
        "nlp_intent_requests_total",
        "Total de solicitudes de clasificación procesadas",
        registry=REGISTRY,
    )
    REQUEST_LATENCY = Histogram(
        "nlp_intent_request_latency_seconds",
        "Latencia de las solicitudes de clasificación en segundos",
        registry=REGISTRY,
    )


__all__ = ["record_request", "export_metrics", "reset_metrics", "CONTENT_TYPE_LATEST"]
