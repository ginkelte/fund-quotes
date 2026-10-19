"""REQ-ADP-003 / AC-10 / EC-006: normalización de valores y fechas chilenas."""

from __future__ import annotations

from datetime import date

import pytest

from fund_quotes.quote import (
    QuoteFormatError,
    normalize_close,
    parse_fecha_es,
    quote_from_texto,
)


@pytest.mark.parametrize(
    ("texto", "fecha", "cierre", "iso"),
    [
        ("$5.054,2279", "15 de octubre de 2026", 5054.2279, "2026-10-15"),
        ("$1.234,5", "1 de septiembre de 2026", 1234.5, "2026-09-01"),
        ("$987,6543", "31 de diciembre de 2025", 987.6543, "2025-12-31"),
    ],
)
def test_ac10_normaliza_formato_chileno(texto, fecha, cierre, iso):
    quote = quote_from_texto(texto, fecha)
    assert quote.close == cierre
    assert quote.date.isoformat() == iso


def test_ac10_acepta_espacios_y_nbsp():
    assert normalize_close("  $ 5.054,2279\u00a0") == 5054.2279


def test_ac10_redondea_half_up_a_cuatro_decimales():
    assert normalize_close("1,00005") == 1.0001
    assert normalize_close("1,00004") == 1.0


def test_redondeo_half_up_no_usa_bankers():
    # float() daría 2.675 -> 2.67; Decimal half-up da 2.6750 sin cambios de escala
    assert normalize_close("2,6750") == 2.675


@pytest.mark.parametrize(
    "texto",
    ["1,234.56", "1,234,567.89", "1.234", "5054", "1.2345e3", "5,05E2", "abc", "", "  ", "$"],
)
def test_ec006_rechaza_formatos_ambiguos_o_no_numericos(texto):
    with pytest.raises(QuoteFormatError):
        normalize_close(texto)


@pytest.mark.parametrize("texto", ["0", "0,0000", "10000000", "10000001,5"])
def test_rechaza_valores_fuera_de_rango(texto):
    with pytest.raises(QuoteFormatError):
        normalize_close(texto)


def test_rechaza_negativos():
    with pytest.raises(QuoteFormatError):
        normalize_close("-5,00")


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("15 de octubre de 2026", date(2026, 10, 15)),
        ("1 de septiembre de 2026", date(2026, 9, 1)),
        ("31 de diciembre de 2025", date(2025, 12, 31)),
        ("3 de febrero de 2024", date(2024, 2, 3)),
        ("Al 15 de octubre de 2026", date(2026, 10, 15)),
    ],
)
def test_parsea_fechas_en_espanol(texto, esperado):
    assert parse_fecha_es(texto) == esperado


@pytest.mark.parametrize(
    "texto", ["15 de octubre", "2026-10-15", "32 de octubre de 2026", "15 de octubr de 2026"]
)
def test_rechaza_fechas_invalidas(texto):
    with pytest.raises(QuoteFormatError):
        parse_fecha_es(texto)
