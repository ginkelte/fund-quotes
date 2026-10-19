"""REQ-PUB-002 / AC-08: página de estado, días hábiles y determinismo."""

from __future__ import annotations

from datetime import date

import pytest

from conftest import feed_de
from fund_quotes import status_page


@pytest.mark.parametrize(
    ("ultimo", "esperado"),
    [
        (date(2026, 10, 15), 2),
        (date(2026, 10, 16), 1),
        (date(2026, 10, 19), 0),
        (date(2026, 10, 8), 7),
        (date(2026, 10, 2), 11),
    ],
)
def test_dias_habiles_lunes_a_viernes(ultimo, esperado):
    assert status_page.dias_habiles(ultimo, date(2026, 10, 19)) == esperado


def test_dias_habiles_no_cuenta_el_dia_del_ultimo_punto():
    assert status_page.dias_habiles(date(2026, 10, 16), date(2026, 10, 19)) == 1


def test_futuro_no_genera_dias_negativos():
    assert status_page.dias_habiles(date(2026, 10, 20), date(2026, 10, 19)) == 0


def test_formato_clp():
    assert status_page.formato_clp(5054.2279) == "5.054,2279"
    assert status_page.formato_clp(2181.18) == "2.181,18"
    assert status_page.formato_clp(1234.5) == "1.234,50"


def _feeds(ultimo_a: date, ultimo_b: date = date(2026, 10, 15)):
    return {
        "CFMITNIPSA": feed_de("CFMITNIPSA", [(ultimo_a, 5054.2279)]),
        "CFINRENTAS": feed_de("CFINRENTAS", [(ultimo_b, 2181.18)]),
    }


def test_ac08_muestra_cierre_fecha_fuente_y_dias():
    html = status_page.render(_feeds(date(2026, 10, 15)), date(2026, 10, 19))
    assert "5.054,2279" in html
    assert "2.181,18" in html
    assert "2026-10-15" in html
    assert "ledgifi:9019" in html
    assert "aindependencia:bolsa" in html
    assert "Al día: 2 días hábiles" in html


def test_ac08_con_ultimo_punto_lejano_entra_en_alerta():
    html = status_page.render(_feeds(date(2026, 10, 8)), date(2026, 10, 19))
    assert "Alerta: 7 días hábiles sin actualización (umbral 3)" in html
    assert 'class="alerta"' in html


def test_determinismo_mismo_feed_y_misma_fecha():
    feeds = _feeds(date(2026, 10, 15))
    primera = status_page.render(feeds, date(2026, 10, 19))
    segunda = status_page.render(feeds, date(2026, 10, 19))
    assert primera == segunda


def test_no_incluye_fecha_ni_hora_de_generacion():
    html = status_page.render(_feeds(date(2026, 10, 15)), date(2026, 10, 19))
    assert "Generado" not in html
    assert "generado" not in html


def test_es_autocontenido_sin_js_ni_assets_externos():
    html = status_page.render(_feeds(date(2026, 10, 15)), date(2026, 10, 19))
    assert "<script" not in html.lower()
    assert "http://" not in html
    assert "https://" not in html
    assert "src=" not in html
    assert "<style>" in html


def test_feed_ausente_muestra_alerta():
    feeds = {"CFMITNIPSA": None, "CFINRENTAS": feed_de("CFINRENTAS", [(date(2026, 10, 15), 2181.18)])}
    html = status_page.render(feeds, date(2026, 10, 19))
    assert "Alerta: sin datos publicados" in html


def test_escapa_contenido_de_los_feeds():
    feed = feed_de(
        "CFMITNIPSA",
        [(date(2026, 10, 15), 5054.2279)],
        name='<b>"FM"</b>',
    )
    html = status_page.render({"CFMITNIPSA": feed, "CFINRENTAS": None}, date(2026, 10, 19))
    assert "<b>" not in html
    assert "&lt;b&gt;" in html
