# Nombre de archivo: metrics.py
# Ubicación de archivo: core/metrics.py
# Descripción: Acumulador simple de métricas de latencia y conteo

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Metrics:
    """Acumulador básico de métricas del servicio."""

    total_requests: int = 0
    total_latency: float = 0.0

    def record(self, latency: float) -> None:
        """Registra una nueva solicitud y su latencia."""
        self.total_requests += 1
        self.total_latency += latency

    def snapshot(self) -> dict[str, float]:
        """Devuelve un resumen con promedio de latencia en ms."""
        promedio = (
            self.total_latency / self.total_requests if self.total_requests else 0.0
        )
        return {
            "total_requests": self.total_requests,
            "average_latency_ms": promedio * 1000,
        }

    def reset(self) -> None:
        """Reinicia los contadores."""
        self.total_requests = 0
        self.total_latency = 0.0
