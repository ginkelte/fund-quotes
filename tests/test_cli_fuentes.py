"""Cadena primaria/respaldo por fondo (§4): quién responde y qué se reporta.

Sin red: los tres adaptadores quedan reemplazados por fixtures vía ``fuentes``.
"""

from __future__ import annotations

from datetime import date

from conftest import correr, escribir_feed, feed_de, leer_json

from fund_quotes.fetch import FetchError


def _args(tmp_path, hoy: str, *extra, fondo=None):
    base = [
        "--out",
        str(tmp_path / "quotes"),
        "--status-page",
        str(tmp_path / "index.html"),
        "--today",
        hoy,
    ]
    if fondo is not None:
        base += ["--fondo", fondo]
    return base + list(extra)


# ── CFINRENTAS: dividendera primaria, aindependencia respaldo ────────────────


def test_cfinrentas_publica_con_dividendera_como_primaria(
    tmp_path, fuentes, capsys, html_dividendera_cfinrentas
):
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_cfinrentas
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 15), 2181.18), (date(2026, 10, 19), 2169.08)]),
    )

    codigo, out, err = correr(_args(tmp_path, "2026-10-22", fondo="CFINRENTAS"), capsys)

    datos = leer_json(ruta)
    assert codigo == 0
    assert err == ""
    assert datos["data"][:2] == [
        {"date": "2026-10-15", "close": 2181.18},
        {"date": "2026-10-19", "close": 2169.08},
    ]
    assert datos["data"][-1] == {"date": "2026-10-22", "close": 2181.73}
    assert datos["updated"] == "2026-10-22"
    assert datos["source"] == "dividendera:CFINRENTAS"
    assert (
        "[OK] CFINRENTAS fecha=2026-10-22 close=2181.73 fuente=dividendera:CFINRENTAS" in out
    )
    assert "[AVISO]" not in out
    # No se consultó el respaldo: una sola petición, a la URL del nemo.
    assert fuentes["llamadas_b"] == 0
    assert fuentes["urls_d"] == ["https://www.dividendera.cl/CFINRENTAS"]


def test_cfinrentas_si_cae_dividendera_usa_independencia_y_avisa(
    tmp_path, fuentes, capsys
):
    fuentes["error_d"] = FetchError("la fuente respondió HTTP 503; se reintentará")
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 14), 2175.45)]),
    )

    codigo, out, _ = correr(_args(tmp_path, "2026-10-19", fondo="CFINRENTAS"), capsys)

    datos = leer_json(ruta)
    assert codigo == 0
    assert datos["data"][-1] == {"date": "2026-10-15", "close": 2181.18}
    assert datos["source"] == "aindependencia:bolsa"
    assert (
        "[AVISO] CFINRENTAS se usó la fuente de respaldo aindependencia:bolsa: "
        "la primaria dividendera:CFINRENTAS falló (primaria dividendera:CFINRENTAS: "
        "la fuente respondió HTTP 503; se reintentará)" in out
    )
    assert "fuente=aindependencia:bolsa" in out
    assert out.index("[AVISO] CFINRENTAS") < out.index("[OK] CFINRENTAS")


def test_cfinrentas_con_ambas_fuentes_caidas_falla_con_los_dos_motivos(
    tmp_path, fuentes, capsys
):
    fuentes["error_d"] = FetchError("la fuente respondió HTTP 503; se reintentará")
    fuentes["error_b"] = FetchError("la fuente respondió HTTP 500; se reintentará")
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 19), 2169.08)]),
    )
    antes = ruta.read_bytes()

    # CFMITNIPSA sigue sano por su primaria: el código de salida es "parcial".
    codigo, out, err = correr(_args(tmp_path, "2026-10-22"), capsys)

    assert codigo == 2
    assert ruta.read_bytes() == antes
    assert "[OK] CFMITNIPSA" in out and "fuente=ledgifi:9019" in out
    falla = next(linea for linea in out.splitlines() if linea.startswith("[FALLA] CFINRENTAS"))
    assert "fuente=dividendera:CFINRENTAS" in falla
    assert "primaria dividendera:CFINRENTAS: la fuente respondió HTTP 503" in falla
    assert "respaldo aindependencia:bolsa: la fuente respondió HTTP 500" in falla
    assert "[FALLA] CFINRENTAS" in err


def test_sin_cambios_reporta_la_fuente_usada(tmp_path, fuentes, capsys, html_dividendera_cfinrentas):
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_cfinrentas
    escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 22), 2181.73)]),
    )

    codigo, out, _ = correr(_args(tmp_path, "2026-10-22", fondo="CFINRENTAS"), capsys)

    assert codigo == 0
    assert (
        "[SIN CAMBIOS] CFINRENTAS fecha=2026-10-22 close=2181.73 "
        "fuente=dividendera:CFINRENTAS motivo=ya_publicado" in out
    )


# ── CFMITNIPSA: ledgifi primaria (NAV), dividendera respaldo ─────────────────


def test_cfmitnipsa_si_cae_ledgifi_usa_dividendera_y_avisa(
    tmp_path, fuentes, capsys, html_dividendera_cfmitnipsa
):
    fuentes["error_a"] = FetchError(
        "la fuente respondió HTTP 429 tras 3 intentos; posible bloqueo del proxy",
        retryable=True,
    )
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_cfmitnipsa
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 15), 5054.2279), (date(2026, 10, 22), 4963.6791)]),
    )

    codigo, out, _ = correr(_args(tmp_path, "2026-10-23", fondo="CFMITNIPSA"), capsys)

    datos = leer_json(ruta)
    assert codigo == 0
    assert datos["data"][:2] == [
        {"date": "2026-10-15", "close": 5054.2279},
        {"date": "2026-10-22", "close": 4963.6791},
    ]
    assert datos["data"][-1] == {"date": "2026-10-23", "close": 4937.2}
    assert datos["source"] == "dividendera:CFMITNIPSA"
    assert (
        "[AVISO] CFMITNIPSA se usó la fuente de respaldo dividendera:CFMITNIPSA" in out
    )
    assert "429" in out
    assert (
        "[OK] CFMITNIPSA fecha=2026-10-23 close=4937.2 fuente=dividendera:CFMITNIPSA" in out
    )
    assert fuentes["urls_d"] == ["https://www.dividendera.cl/CFMITNIPSA"]


def test_cfmitnipsa_con_respaldo_publica_igual_sin_backfill(
    tmp_path, fuentes, capsys, html_dividendera_cfmitnipsa
):
    """El respaldo no trae serie de índice: el backfill se degrada a aviso."""

    fuentes["error_a"] = FetchError("la fuente respondió HTTP 429", retryable=True)
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_cfmitnipsa
    escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 22), 4963.6791)]),
    )

    codigo, out, err = correr(
        _args(tmp_path, "2026-10-23", "--backfill", "10", fondo="CFMITNIPSA"), capsys
    )

    assert codigo == 0
    assert err == ""
    assert "[OK] CFMITNIPSA fecha=2026-10-23" in out
    assert "[AVISO] CFMITNIPSA backfill:" in out
    assert not (tmp_path / "quotes" / "CFMITNIPSA.backfill.json").exists()


def test_cfmitnipsa_con_ambas_caidas_no_publica(tmp_path, fuentes, capsys):
    fuentes["error_a"] = FetchError("la fuente respondió HTTP 429", retryable=True)
    fuentes["error_d"] = FetchError("la fuente respondió HTTP 503", retryable=True)
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 22), 4963.6791)]),
    )
    antes = ruta.read_bytes()

    codigo, out, err = correr(_args(tmp_path, "2026-10-23", fondo="CFMITNIPSA"), capsys)

    assert codigo == 1
    assert ruta.read_bytes() == antes
    falla = next(linea for linea in out.splitlines() if linea.startswith("[FALLA] CFMITNIPSA"))
    assert "fuente=ledgifi:9019" in falla
    assert "primaria ledgifi:9019: no se pudo obtener la cuota de CFMITNIPSA" in falla
    assert "HTTP 429" in falla
    assert "respaldo dividendera:CFMITNIPSA: la fuente respondió HTTP 503" in falla
    assert "[FALLA] CFMITNIPSA" in err


def test_la_pagina_de_estado_muestra_la_cadena(
    tmp_path, fuentes, capsys, html_dividendera_cfinrentas
):
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_cfinrentas
    escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 22), 4963.6791)]),
    )
    escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 19), 2169.08)]),
    )

    codigo, _, _ = correr(_args(tmp_path, "2026-10-22"), capsys)

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert codigo == 0
    assert "dividendera:CFINRENTAS (respaldo: aindependencia:bolsa)" in html
    assert "ledgifi:9019 (respaldo: dividendera:CFMITNIPSA)" in html
    assert 'class="alerta"' not in html
