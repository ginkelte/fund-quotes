"""REQ-GRD-001 / EC-002: anomalía de 5% y fechas implausibles."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from fund_quotes import guards
from fund_quotes.quote import Quote


def test_sin_punto_previo_la_guarda_no_aplica():
    assert guards.validar_anomalia(Quote(date(2026, 10, 15), 5054.2279), None) is None


def test_variacion_bajo_el_umbral_se_acepta():
    anterior = Quote(date(2026, 10, 14), 2175.45)
    nuevo = Quote(date(2026, 10, 15), 2181.18)
    variacion = guards.validar_anomalia(nuevo, anterior)
    assert variacion is not None
    assert abs(variacion) < Decimal("5.00")


def test_exactamente_5_por_ciento_se_acepta():
    anterior = Quote(date(2026, 10, 14), 1000.0)
    nuevo = Quote(date(2026, 10, 15), 1050.0)
    assert guards.validar_anomalia(nuevo, anterior) == Decimal("5.0")


def test_ac06_salto_de_10_32_por_ciento_se_rechaza():
    anterior = Quote(date(2026, 10, 14), 2175.45)
    nuevo = Quote(date(2026, 10, 15), 2400.00)
    with pytest.raises(guards.AnomaliaDetectada) as excinfo:
        guards.validar_anomalia(nuevo, anterior)
    assert guards.formato_pct(excinfo.value.variacion, signo=True) == "+10,32%"
    assert guards.formato_pct(excinfo.value.umbral) == "5,00%"


def test_baja_mayor_al_umbral_tambien_se_rechaza():
    anterior = Quote(date(2026, 10, 14), 2000.0)
    nuevo = Quote(date(2026, 10, 15), 1800.0)
    with pytest.raises(guards.AnomaliaDetectada) as excinfo:
        guards.validar_anomalia(nuevo, anterior)
    assert guards.formato_pct(excinfo.value.variacion, signo=True) == "-10,00%"


def test_mismo_dia_no_evalua_anomalia():
    anterior = Quote(date(2026, 10, 15), 1000.0)
    assert guards.validar_anomalia(Quote(date(2026, 10, 15), 2000.0), anterior) is None


def test_formato_pct_chileno():
    assert guards.formato_pct(Decimal("10.32"), signo=True) == "+10,32%"
    assert guards.formato_pct(Decimal("5.00")) == "5,00%"
    assert guards.formato_pct(Decimal("-1.5")) == "-1,50%"
    assert guards.formato_pct(Decimal(0)) == "0,00%"


def test_fecha_de_manana_es_aceptable():
    hoy = date(2026, 10, 19)
    guards.validar_fecha(Quote(date(2026, 10, 20), 1000.0), hoy)


def test_ec002_fecha_posterior_a_manana_es_implausible():
    hoy = date(2026, 10, 19)
    with pytest.raises(guards.FechaImplausible) as excinfo:
        guards.validar_fecha(Quote(date(2026, 10, 25), 1000.0), hoy)
    assert "fecha implausible" in str(excinfo.value)
