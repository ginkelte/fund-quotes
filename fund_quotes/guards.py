"""Guardas de calidad: fechas implausibles y saltos mayores al umbral.

Este módulo solo decide si un punto se rechaza; no publica ni reintenta.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from .quote import Quote

UMBRAL_PCT = Decimal("5.00")


class GuardError(Exception):
    """Un punto rechazado por una guarda. Siempre corresponde al código 3."""


class FechaImplausible(GuardError):
    def __init__(self, fecha: date, hoy: date) -> None:
        self.fecha = fecha
        self.hoy = hoy
        super().__init__(
            f"fecha implausible: {fecha.isoformat()} es posterior a hoy + 1 día "
            f"({(hoy + timedelta(days=1)).isoformat()})"
        )


class AnomaliaDetectada(GuardError):
    def __init__(self, variacion: Decimal, umbral: Decimal, fecha: date) -> None:
        self.variacion = variacion
        self.umbral = umbral
        self.fecha = fecha
        super().__init__(
            f"variación {formato_pct(variacion, signo=True)} supera el umbral de "
            f"{formato_pct(umbral)}"
        )


def formato_pct(valor: Decimal, *, signo: bool = False) -> str:
    """``Decimal('10.32')`` -> ``'+10,32%'`` con ``signo``; si no, ``'5,00%'``."""

    redondeado = valor.quantize(Decimal("0.01"))
    prefijo = "+" if signo and redondeado > 0 else ""
    return f"{prefijo}{redondeado:.2f}%".replace(".", ",")


def validar_fecha(quote: Quote, hoy: date) -> None:
    """EC-002: una fecha posterior a hoy + 1 día se rechaza."""

    if quote.date > hoy + timedelta(days=1):
        raise FechaImplausible(quote.date, hoy)


def variacion_pct(quote: Quote, anterior: Quote) -> Decimal:
    return (Decimal(str(quote.close)) / Decimal(str(anterior.close)) - Decimal(1)) * Decimal(100)


def validar_anomalia(quote: Quote, anterior: Quote | None) -> Decimal | None:
    """REQ-GRD-001: rechaza un salto de más de 5,00% contra el punto previo.

    Sin punto previo la guarda no aplica (EC-004).
    """

    if anterior is None or quote.date <= anterior.date:
        return None
    variacion = variacion_pct(quote, anterior)
    if abs(variacion) > UMBRAL_PCT:
        raise AnomaliaDetectada(variacion, UMBRAL_PCT, quote.date)
    return variacion
