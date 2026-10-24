"""Fuente C (Dividendera): cierres embebidos en la app Next.js.

Sin red: los fixtures son recortes verbatim de la ficha real (~110 KB, cientos de
objetos ``nemo``/``fecha``/``cierre``) y las variantes sintéticas se arman con el
mismo formato de payload.
"""

from __future__ import annotations

import re

import pytest

from fund_quotes.sources import SourceError, dividendera

MIN = dividendera.MIN_BYTES


def _pagina(objetos: str, relleno: int = 120_000) -> str:
    """Página con el payload embebido y relleno suficiente para pasar el piso."""

    cuerpo = '<script>self.__next_f.push([1,"' + objetos + '"])</script>'
    return "<html><body>" + cuerpo + " " * relleno + "</body></html>"


def _objeto(nemo: str, fecha: str, cierre: str, ident: int = 1) -> str:
    """Objeto de precio con las comillas escapadas, como en el chunk real."""

    return (
        f'{{\\"id\\":{ident},\\"nemo\\":\\"{nemo}\\",'
        f'\\"fecha\\":\\"$D{fecha}T00:00:00.000Z\\",'
        f'\\"cierre\\":{cierre},\\"volumen\\":123456.78}}'
    )


# ── Parseo de los fixtures verbatim ──────────────────────────────────────────


def test_cfinrentas_escapado(html_dividendera_cfinrentas):
    quote = dividendera.parse_quote(html_dividendera_cfinrentas, "CFINRENTAS")
    assert quote.date.isoformat() == "2026-10-22"
    assert quote.close == 2181.73


def test_cfmitnipsa_escapado(html_dividendera_cfmitnipsa):
    quote = dividendera.parse_quote(html_dividendera_cfmitnipsa, "CFMITNIPSA")
    assert quote.date.isoformat() == "2026-10-23"
    assert quote.close == 4937.2


@pytest.mark.parametrize(
    ("fixture", "nemo", "fecha", "close"),
    [
        ("html_dividendera_cfinrentas", "CFINRENTAS", "2026-10-22", 2181.73),
        ("html_dividendera_cfmitnipsa", "CFMITNIPSA", "2026-10-23", 4937.2),
    ],
)
def test_acepta_la_variante_sin_escapar(request, fixture, nemo, fecha, close):
    """El chunk puede traer las comillas sin escapar: mismo resultado."""

    html = request.getfixturevalue(fixture)
    sin_escapar = re.sub(r'\\+"', '"', html)
    assert sin_escapar != html
    assert '\\"' not in sin_escapar
    # Al sacar los backslashes el recorte queda bajo el piso de tamaño: se rellena
    # para probar el parseo, no el control de tamaño.
    if len(sin_escapar.encode("utf-8")) < dividendera.MIN_BYTES:
        sin_escapar += " " * dividendera.MIN_BYTES
    quote = dividendera.parse_quote(sin_escapar, nemo)
    assert (quote.date.isoformat(), quote.close) == (fecha, close)


def test_los_dos_fixtures_no_se_mezclan(html_dividendera_cfinrentas):
    """El nemo ancla el parseo: el fixture de CFINRENTAS no sirve para el otro."""

    with pytest.raises(SourceError) as excinfo:
        dividendera.parse_quote(html_dividendera_cfinrentas, "CFMITNIPSA")
    assert "dividendera no trae cierres para CFMITNIPSA" in str(excinfo.value)


# ── Selección del punto ──────────────────────────────────────────────────────


def test_elige_la_fecha_maxima_con_puntos_desordenados():
    html = _pagina(
        "["
        + ",".join(
            [
                _objeto("CFINRENTAS", "2026-10-22", "2181.73", 3),
                _objeto("CFINRENTAS", "2017-01-05", "1150.6", 1),
                _objeto("CFINRENTAS", "2026-10-19", "2169.076", 2),
            ]
        )
        + "]"
    )
    quote = dividendera.parse_quote(html, "CFINRENTAS")
    assert quote.date.isoformat() == "2026-10-22"
    assert quote.close == 2181.73


def test_la_fecha_es_el_dia_bursatil_literal_sin_pasar_por_utc():
    """``$D2026-10-22T23:30:00.000Z`` es el 22-10 en Chile, no el 23."""

    html = _pagina(
        '{"id":1,"nemo":"CFINRENTAS","fecha":"$D2026-10-22T23:30:00.000Z",'
        '"cierre":2181.73,"volumen":1}'
    )
    quote = dividendera.parse_quote(html, "CFINRENTAS")
    assert quote.date.isoformat() == "2026-10-22"


def test_no_cruza_objetos_para_armar_un_punto():
    """``nemo`` en un objeto y ``cierre`` en otro no son un punto válido."""

    html = _pagina(
        '[{"nemo":"CFINRENTAS","nombre":"x"},{"fecha":"$D2026-10-22T00:00:00.000Z",'
        '"cierre":2181.73}]'
    )
    with pytest.raises(SourceError) as excinfo:
        dividendera.parse_quote(html, "CFINRENTAS")
    assert "no trae cierres para CFINRENTAS" in str(excinfo.value)


def test_ignora_cierres_no_positivos():
    html = _pagina(
        "["
        + _objeto("CFINRENTAS", "2026-10-22", "0", 2)
        + ","
        + _objeto("CFINRENTAS", "2026-10-19", "2169.076", 1)
        + "]"
    )
    quote = dividendera.parse_quote(html, "CFINRENTAS")
    assert quote.date.isoformat() == "2026-10-19"


# ── Fallos accionables ───────────────────────────────────────────────────────


def test_nemo_ausente_falla_con_motivo_accionable():
    html = _pagina(_objeto("OTROFONDO", "2026-10-22", "1.5"))
    with pytest.raises(SourceError) as excinfo:
        dividendera.parse_quote(html, "CFINRENTAS")
    assert (
        "dividendera no trae cierres para CFINRENTAS (posible cambio de nemo o de layout)"
        in str(excinfo.value)
    )


def test_pagina_de_bloqueo_falla():
    html = _pagina("<html>Vercel Security Checkpoint</html>")
    with pytest.raises(SourceError) as excinfo:
        dividendera.parse_quote(html, "CFINRENTAS")
    assert "bloqueo" in str(excinfo.value)
    assert "vercel security checkpoint" in str(excinfo.value)


def test_cuerpo_pequeno_falla():
    with pytest.raises(SourceError) as excinfo:
        dividendera.parse_quote("<html>error</html>", "CFINRENTAS")
    assert "demasiado pequeña" in str(excinfo.value)
    assert str(MIN) in str(excinfo.value)


def test_respuesta_vacia_falla():
    with pytest.raises(SourceError):
        dividendera.parse_quote("", "CFINRENTAS")


@pytest.mark.parametrize("nemo", ["", "cfinrentas", "../CFINRENTAS", "CFIN RENTAS", "A" * 16])
def test_nemo_invalido_falla_antes_de_armar_la_url(nemo):
    with pytest.raises(SourceError) as excinfo:
        dividendera.url_de(nemo)
    assert "nemo inválido" in str(excinfo.value)


# ── Descarga ─────────────────────────────────────────────────────────────────


def test_cargar_pide_la_url_del_nemo_con_el_piso_de_tamano(
    monkeypatch, html_dividendera_cfinrentas
):
    llamadas: list[tuple[str, int]] = []

    def falso(url, *, min_bytes, **kwargs):
        llamadas.append((url, min_bytes))
        return html_dividendera_cfinrentas

    monkeypatch.setattr(dividendera, "fetch_text", falso)
    serie, indice = dividendera.cargar("CFINRENTAS")

    # El adaptador no recorta: entrega todos los cierres que trae la ficha.
    assert len(serie) > 1
    assert serie[-1].close == 2181.73
    assert serie[-1].date.isoformat() == "2026-10-22"
    assert serie == sorted(serie, key=lambda punto: punto.date)
    assert indice is None
    assert llamadas == [("https://www.dividendera.cl/CFINRENTAS", MIN)]
