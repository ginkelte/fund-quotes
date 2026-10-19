"""Fuente B (Independencia): serie BOLSA y fecha derivada en UTC."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from conftest import html_independencia_con
from fund_quotes.sources import SourceError, aindependencia

MS_15_OCT = 1792022400000
MS_14_OCT = 1791936000000


def test_ac01b_toma_la_serie_bolsa_del_fixture(html_independencia):
    quote = aindependencia.parse_quote(html_independencia)
    assert quote.date.isoformat() == "2026-10-15"
    assert quote.close == 2181.18


def test_ac01b_fecha_derivada_en_utc_no_en_hora_de_chile():
    assert (
        datetime.fromtimestamp(MS_15_OCT / 1000, tz=timezone.utc).date().isoformat()
        == "2026-10-15"
    )
    quote = aindependencia.parse_quote(
        html_independencia_con(
            open("tests/fixtures/aindependencia_fondos.html", encoding="utf-8").read(),
            [[MS_14_OCT, 2175.45], [MS_15_OCT, 2181.18]],
        )
    )
    assert quote.date.isoformat() == "2026-10-15"


def test_ignora_valor_libro(html_independencia):
    datos = aindependencia.extraer_chart_data(html_independencia)
    nombres = [serie["name"] for serie in datos["series"]]
    assert "BOLSA" in nombres and "Valor Libro" in nombres
    quote = aindependencia.parse_quote(html_independencia)
    assert quote.close == pytest.approx(2181.18)
    assert quote.close != pytest.approx(238.947)


def test_elige_el_punto_de_mayor_epoch_sin_importar_el_orden(html_independencia):
    html = html_independencia_con(
        html_independencia,
        [
            [MS_15_OCT, 2181.18],
            [MS_14_OCT, 2175.45],
            [MS_15_OCT - 86400000 * 5, 2100.00],
        ],
    )
    quote = aindependencia.parse_quote(html)
    assert quote.close == 2181.18
    assert quote.date.isoformat() == "2026-10-15"


def test_serie_bolsa_ausente_falla(html_independencia):
    inicio = html_independencia.find('"name":"BOLSA"')
    assert inicio > 0
    html = html_independencia.replace('"name":"BOLSA"', '"name":"OTRA"')
    with pytest.raises(SourceError) as excinfo:
        aindependencia.parse_quote(html)
    assert "no se encontró la serie BOLSA" in str(excinfo.value)


def test_marcador_ausente_falla():
    with pytest.raises(SourceError) as excinfo:
        aindependencia.parse_quote("<html><body>nada</body></html>")
    assert "vfiChartData" in str(excinfo.value)


def test_json_truncado_falla():
    html = '<script>var vfiChartData = {"series":[{"name":"BOLSA","data":[[1,2]]</script>'
    with pytest.raises(SourceError) as excinfo:
        aindependencia.parse_quote(html)
    assert "truncado" in str(excinfo.value)


def test_json_invalido_falla_sin_eval():
    html = '<script>var vfiChartData = {"series": [alert(1)]};</script>'
    with pytest.raises(SourceError) as excinfo:
        aindependencia.parse_quote(html)
    assert "no es JSON válido" in str(excinfo.value)


def test_respuesta_vacia_falla():
    with pytest.raises(SourceError):
        aindependencia.parse_quote("")


def test_cargar_no_expone_indice(monkeypatch, html_independencia):
    monkeypatch.setattr(aindependencia, "fetch_text", lambda *a, **k: html_independencia)
    quote, indice = aindependencia.cargar(con_indice=True)
    assert quote.close == 2181.18
    assert indice is None
