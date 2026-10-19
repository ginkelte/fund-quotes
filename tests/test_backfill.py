"""Unit tests de ``fund_quotes.backfill``: bordes de la derivación, sin red ni disco."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest

from fund_quotes import catalog, store
from fund_quotes.backfill import (
    BACKFILL_MAX,
    BACKFILL_MIN,
    BackfillError,
    construir_backfill,
)
from fund_quotes.quote import Quote
from fund_quotes.sources.ledgifi import IndexPoint

FUND = catalog.get_fund("CFMITNIPSA")
DIA = date(2026, 10, 15)
CUATRO_DECIMALES = Decimal("0.0001")


def _feed(close: float = 5054.2279, fecha: date = DIA) -> store.Feed:
    return store.Feed(
        ticker=FUND.ticker,
        name=FUND.name,
        currency=store.CURRENCY,
        source=FUND.source,
        updated=fecha,
        data=[Quote(date=fecha, close=close)],
    )


def _indice(cantidad: int, fin: date = DIA) -> list[IndexPoint]:
    """Serie ascendente diaria que termina en ``fin``, con valores crecientes."""

    inicio = fin - timedelta(days=cantidad - 1)
    return [
        IndexPoint(date=inicio + timedelta(days=posicion), value=Decimal(100 + posicion))
        for posicion in range(cantidad)
    ]


def _esperado(close: float, valor: Decimal, indice_ultimo: Decimal) -> Decimal:
    return (Decimal(str(close)) * valor / indice_ultimo).quantize(
        CUATRO_DECIMALES, rounding=ROUND_HALF_UP
    )


def test_n_uno_deriva_un_solo_punto():
    indice = _indice(4)
    feed = construir_backfill(_feed(), indice, 1, FUND)

    assert len(feed.data) == 1
    assert feed.data[0].date == DIA - timedelta(days=1)
    assert feed.updated == feed.data[0].date
    assert feed.ticker == FUND.ticker and feed.name == FUND.name
    assert feed.source == f"{FUND.source}#indice"
    esperado = _esperado(5054.2279, indice[-2].value, indice[-1].value)
    assert Decimal(str(feed.data[0].close)) == esperado


def test_n_maximo_usa_los_ultimos_puntos_anteriores():
    indice = _indice(200)
    feed = construir_backfill(_feed(), indice, BACKFILL_MAX, FUND)

    assert len(feed.data) == BACKFILL_MAX
    assert feed.data[0].date == indice[-BACKFILL_MAX - 1].date
    assert feed.data[-1].date == DIA - timedelta(days=1)
    assert feed.updated == feed.data[-1].date
    fechas = [punto.date for punto in feed.data]
    assert fechas == sorted(fechas) and len(fechas) == len(set(fechas))


@pytest.mark.parametrize("n", [0, BACKFILL_MIN - 1, BACKFILL_MAX + 1, 1000])
def test_n_fuera_de_rango_levanta_backfill_error(n):
    with pytest.raises(BackfillError) as excinfo:
        construir_backfill(_feed(), _indice(200), n, FUND)
    assert "fuera de rango" in str(excinfo.value)


def test_indice_con_un_solo_punto_no_alcanza():
    indice = [IndexPoint(date=DIA, value=Decimal(100))]
    with pytest.raises(BackfillError) as excinfo:
        construir_backfill(_feed(), indice, 1, FUND)
    assert "excede los 0 puntos" in str(excinfo.value)


def test_fechas_duplicadas_no_duplican_puntos_y_gana_la_ultima():
    indice = _indice(5)
    repetida = DIA - timedelta(days=2)
    indice.insert(3, IndexPoint(date=repetida, value=Decimal(999)))

    feed = construir_backfill(_feed(), indice, 3, FUND)

    fechas = [punto.date for punto in feed.data]
    assert len(fechas) == 3 and len(set(fechas)) == 3
    duplicado = next(punto for punto in feed.data if punto.date == repetida)
    esperado = _esperado(5054.2279, Decimal(999), indice[-1].value)
    assert Decimal(str(duplicado.close)) == esperado


def test_sin_punto_oficial_levanta_backfill_error():
    with pytest.raises(BackfillError) as excinfo:
        construir_backfill(None, _indice(3), 1, FUND)
    assert "no tiene punto oficial" in str(excinfo.value)


def test_indice_sin_la_fecha_del_ultimo_punto_falla():
    indice = [
        IndexPoint(date=DIA - timedelta(days=2), value=Decimal(100)),
        IndexPoint(date=DIA - timedelta(days=1), value=Decimal(110)),
    ]
    with pytest.raises(BackfillError) as excinfo:
        construir_backfill(_feed(), indice, 1, FUND)
    assert DIA.isoformat() in str(excinfo.value)


def test_indice_cero_en_la_fecha_oficial_falla():
    indice = [
        IndexPoint(date=DIA - timedelta(days=1), value=Decimal(90)),
        IndexPoint(date=DIA, value=Decimal(0)),
    ]
    with pytest.raises(BackfillError) as excinfo:
        construir_backfill(_feed(), indice, 1, FUND)
    assert "no es un valor positivo" in str(excinfo.value)
