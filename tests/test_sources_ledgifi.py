"""Fuente A (LedgiFi): tabla de series, cuota y serie de índice."""

from __future__ import annotations

import pytest
from conftest import tabla_ledgifi

from fund_quotes.sources import SourceError, ledgifi


def test_ac01_parsea_la_cuota_del_fixture_real(html_ledgifi):
    quote = ledgifi.parse_quote(html_ledgifi)
    assert quote.date.isoformat() == "2026-10-15"
    assert quote.close == 5054.2279


def test_ac10_parsea_cada_ejemplo_del_esquema():
    casos = [
        ("$5.054,2279", "15 de octubre de 2026", 5054.2279, "2026-10-15"),
        ("$1.234,5", "1 de septiembre de 2026", 1234.5, "2026-09-01"),
        ("$987,6543", "31 de diciembre de 2025", 987.6543, "2025-12-31"),
    ]
    for texto, fecha, cierre, iso in casos:
        quote = ledgifi.parse_quote(tabla_ledgifi(texto, fecha))
        assert quote.close == cierre
        assert quote.date.isoformat() == iso


def test_usa_el_texto_sr_only_y_no_duplica_el_valor():
    # La celda real trae el valor dos veces (sr-only + visual); el parser debe
    # tomar uno solo y no "$5.054,2279$5.054,2279".
    html = tabla_ledgifi("$5.054,2279", "15 de octubre de 2026")
    assert ledgifi.parse_quote(html).close == 5054.2279


def test_ac04_sin_fila_unica_falla_con_motivo_accionable():
    html = tabla_ledgifi(serie="B")
    with pytest.raises(SourceError) as excinfo:
        ledgifi.parse_quote(html)
    assert "no se encontró la cuota de CFMITNIPSA" in str(excinfo.value)


def test_sin_columna_valor_cuota_falla():
    html = "<html><body><table><tr><th>Serie</th></tr><tr><td>UNICA</td></tr></table></body></html>"
    with pytest.raises(SourceError) as excinfo:
        ledgifi.parse_quote(html)
    assert "Valor cuota" in str(excinfo.value)


def test_ac10b_valor_ambiguo_falla_con_error_de_formato():
    html = tabla_ledgifi("1,234.56")
    with pytest.raises(SourceError) as excinfo:
        ledgifi.parse_quote(html)
    assert "formato inválido" in str(excinfo.value)
    assert "ambiguo" in str(excinfo.value)


def test_respuesta_corta_falla():
    with pytest.raises(SourceError):
        ledgifi.parse_quote("<html></html>")


def test_ac11_serie_de_indice_tiene_156_puntos(html_ledgifi):
    indice = ledgifi.parse_index(html_ledgifi)
    assert len(indice) == 156
    assert indice[0].date.isoformat() == "2016-01-01"
    assert indice[-1].date.isoformat() == "2026-10-15"
    assert str(indice[-1].value) == "173.8262101046597"
    assert indice == sorted(indice, key=lambda punto: punto.date)


def test_indice_conserva_precision_completa(html_ledgifi):
    indice = ledgifi.parse_index(html_ledgifi)
    # El índice no se redondea a 4 decimales: se usa como razón del backfill.
    assert len(str(indice[-1].value).split(".")[1]) > 10


def test_indice_ausente_falla():
    with pytest.raises(SourceError) as excinfo:
        ledgifi.parse_index("<html><body>sin serie</body></html>")
    assert "serie de índice" in str(excinfo.value)


def test_cargar_hace_una_sola_peticion(monkeypatch, html_ledgifi):
    llamadas = []

    def falso_fetch(*args, **kwargs):
        llamadas.append(kwargs)
        return html_ledgifi

    monkeypatch.setattr(ledgifi, "fetch_text", falso_fetch)
    quote, indice = ledgifi.cargar(con_indice=True)
    assert len(llamadas) == 1
    assert quote.close == 5054.2279
    assert indice is not None and len(indice) == 156
    assert llamadas[0]["headers"] == {"x-return-format": "html"}
    assert ledgifi.PROXY_URL.startswith("https://r.jina.ai/https://ledgifi.com/")


def test_cargar_sin_indice_no_lo_parsea(monkeypatch, html_ledgifi):
    monkeypatch.setattr(ledgifi, "fetch_text", lambda *a, **k: html_ledgifi)
    _, indice = ledgifi.cargar()
    assert indice is None
