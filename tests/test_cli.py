"""Criterios de aceptación de punta a punta, sin red (fixtures + monkeypatch)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest

from conftest import (
    correr,
    escribir_feed,
    feed_de,
    html_independencia_con,
    leer_json,
    puntos_habiles,
    tabla_ledgifi,
)
from fund_quotes import catalog, store
from fund_quotes.fetch import FetchError
from fund_quotes.quote import Quote

HOY = "2026-10-19"


def _hash(ruta) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _args(tmp_path, *extra, fondo=None):
    base = [
        "--out",
        str(tmp_path / "quotes"),
        "--status-page",
        str(tmp_path / "index.html"),
        "--today",
        HOY,
    ]
    if fondo is not None:
        base += ["--fondo", fondo]
    return base + list(extra)


# ── AC-01 / AC-01b ───────────────────────────────────────────────────────────


def test_ac01_publica_la_fecha_de_la_fuente(tmp_path, fuentes, capsys):
    escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 13), 5054.0), (date(2026, 10, 14), 5054.0853)]),
    )
    codigo, out, _ = correr(_args(tmp_path, fondo="CFMITNIPSA"), capsys)

    datos = leer_json(tmp_path / "quotes" / "CFMITNIPSA.json")
    assert codigo == 0
    assert datos["updated"] == "2026-10-15"
    assert datos["data"][-1] == {"date": "2026-10-15", "close": 5054.2279}
    assert all(punto["date"] != HOY for punto in datos["data"])
    assert datos["data"][:2] == [
        {"date": "2026-10-13", "close": 5054.0},
        {"date": "2026-10-14", "close": 5054.0853},
    ]
    assert "[OK] CFMITNIPSA fecha=2026-10-15 close=5054.2279 fuente=ledgifi:9019" in out


def test_ac01b_publica_cfinrentas_con_fecha_utc(tmp_path, fuentes, capsys):
    codigo, out, _ = correr(_args(tmp_path, fondo="CFINRENTAS"), capsys)
    datos = leer_json(tmp_path / "quotes" / "CFINRENTAS.json")
    assert codigo == 0
    assert datos["data"] == [{"date": "2026-10-15", "close": 2181.18}]
    assert datos["source"] == "aindependencia:bolsa"
    assert "close=2181.18" in out


def test_ac01b_no_usa_valor_libro(tmp_path, fuentes, capsys):
    correr(_args(tmp_path, fondo="CFINRENTAS"), capsys)
    datos = leer_json(tmp_path / "quotes" / "CFINRENTAS.json")
    assert abs(datos["data"][0]["close"] - 238.947) > 1


# ── AC-02 ────────────────────────────────────────────────────────────────────


def test_ac02_dos_corridas_no_modifican_el_feed(tmp_path, fuentes, capsys):
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 15), 5054.2279)]),
    )
    antes = _hash(ruta)

    codigo1, out1, _ = correr(_args(tmp_path, fondo="CFMITNIPSA"), capsys)
    hash1 = _hash(ruta)
    codigo2, out2, _ = correr(_args(tmp_path, fondo="CFMITNIPSA"), capsys)

    assert (codigo1, codigo2) == (0, 0)
    assert hash1 == antes == _hash(ruta)
    assert "[SIN CAMBIOS]" in out1 and "[SIN CAMBIOS]" in out2
    fechas = [punto["date"] for punto in leer_json(ruta)["data"]]
    assert len(fechas) == len(set(fechas))


def test_ac02_la_segunda_corrida_no_reescribe_y_no_duplica(tmp_path, fuentes, capsys):
    correr(_args(tmp_path, fondo="CFINRENTAS"), capsys)
    ruta = tmp_path / "quotes" / "CFINRENTAS.json"
    antes = _hash(ruta)
    correr(_args(tmp_path, fondo="CFINRENTAS"), capsys)
    assert _hash(ruta) == antes
    assert len(leer_json(ruta)["data"]) == 1


# ── AC-03 ────────────────────────────────────────────────────────────────────


def test_ac03_conserva_los_100_puntos_previos(tmp_path, fuentes, capsys):
    previos = puntos_habiles(100, date(2026, 10, 14), 2175.45)
    ruta = escribir_feed(tmp_path / "quotes" / "CFINRENTAS.json", feed_de("CFINRENTAS", previos))
    antes = leer_json(ruta)["data"]

    codigo, _, _ = correr(_args(tmp_path, fondo="CFINRENTAS"), capsys)
    despues = leer_json(ruta)["data"]
    assert codigo == 0
    assert len(despues) == 101
    assert despues[:100] == antes
    assert despues[-1] == {"date": "2026-10-15", "close": 2181.18}


# ── AC-04 ────────────────────────────────────────────────────────────────────


def test_ac04_fuente_sin_la_cuota_falla_sin_inventar(tmp_path, fuentes, capsys):
    fuentes["a"] = tabla_ledgifi(serie="B")
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 13), 5054.0), (date(2026, 10, 14), 5054.0853)]),
    )
    antes = ruta.read_bytes()

    codigo, out, err = correr(_args(tmp_path, fondo="CFMITNIPSA"), capsys)
    assert codigo == 1
    assert "no se encontró la cuota de CFMITNIPSA" in (out + err)
    assert ruta.read_bytes() == antes
    assert len(leer_json(ruta)["data"]) == 2
    assert all(punto["date"] != HOY for punto in leer_json(ruta)["data"])


# ── AC-05 ────────────────────────────────────────────────────────────────────


def test_ac05_si_una_fuente_cae_se_publica_la_otra(tmp_path, fuentes, capsys):
    fuentes["error_a"] = FetchError(
        "la fuente respondió HTTP 429 tras 3 intentos; posible bloqueo del proxy",
        retryable=True,
    )
    ruta_a = escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 14), 5054.0853)]),
    )
    antes_a = ruta_a.read_bytes()

    codigo, out, err = correr(_args(tmp_path), capsys)

    assert codigo == 2
    assert leer_json(tmp_path / "quotes" / "CFINRENTAS.json")["data"][-1] == {
        "date": "2026-10-15",
        "close": 2181.18,
    }
    assert ruta_a.read_bytes() == antes_a
    assert "[FALLA] CFMITNIPSA fuente=ledgifi:9019" in out
    assert "[FALLA] CFMITNIPSA" in err
    assert "[OK] CFINRENTAS" in out


# ── AC-06 ────────────────────────────────────────────────────────────────────


def _html_2400(html_independencia):
    return html_independencia_con(html_independencia, [[1792022400000, 2400.00]])


def test_ac06_anomalia_rechazada_sin_flags(tmp_path, fuentes, capsys, html_independencia):
    fuentes["b"] = _html_2400(html_independencia)
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 14), 2175.45)]),
    )
    antes = ruta.read_bytes()

    codigo, out, _ = correr(_args(tmp_path, fondo="CFINRENTAS"), capsys)

    assert codigo == 3
    assert ruta.read_bytes() == antes
    assert len(leer_json(ruta)["data"]) == 1
    assert "[ANOMALIA] CFINRENTAS" in out
    assert "+10,32%" in out and "5,00%" in out
    assert not (tmp_path / "quotes" / "CFINRENTAS.backfill.json").exists()


def test_ac06_force_anomaly_escribe_y_registra(tmp_path, fuentes, capsys, html_independencia):
    fuentes["b"] = _html_2400(html_independencia)
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 14), 2175.45)]),
    )

    codigo, out, _ = correr(_args(tmp_path, "--force-anomaly", fondo="CFINRENTAS"), capsys)

    datos = leer_json(ruta)
    assert codigo == 0
    assert len(datos["data"]) == 2
    assert datos["data"][-1] == {"date": "2026-10-15", "close": 2400.0}
    assert "[AVISO]" in out and "forzada" in out


# ── AC-11 ────────────────────────────────────────────────────────────────────


def test_ac11_backfill_no_contamina_el_feed_oficial(tmp_path, fuentes, capsys):
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 15), 5054.2279)]),
    )
    codigo, out, _ = correr(_args(tmp_path, "--backfill", "30", fondo="CFMITNIPSA"), capsys)

    oficial = leer_json(ruta)
    derivado = leer_json(tmp_path / "quotes" / "CFMITNIPSA.backfill.json")
    assert codigo == 0
    assert len(oficial["data"]) == 1
    assert len(derivado["data"]) == 30
    assert all(punto["date"] < "2026-10-15" for punto in derivado["data"])
    assert "indice" in derivado["source"]
    assert derivado["updated"] == derivado["data"][-1]["date"]

    indice = {punto.date: punto.value for punto in _indice_ledgifi(fuentes["a"])}
    ultimo = indice[date(2026, 10, 15)]
    for punto in derivado["data"]:
        esperado = (
            Decimal("5054.2279") * indice[date.fromisoformat(punto["date"])] / ultimo
        ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        assert Decimal(str(punto["close"])) == esperado


def _indice_ledgifi(html):
    from fund_quotes.sources import ledgifi

    return ledgifi.parse_index(html)


def test_ac11_backfill_es_determinista(tmp_path, fuentes, capsys):
    escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 15), 5054.2279)]),
    )
    correr(_args(tmp_path, "--backfill", "10", fondo="CFMITNIPSA"), capsys)
    ruta = tmp_path / "quotes" / "CFMITNIPSA.backfill.json"
    antes = _hash(ruta)
    correr(_args(tmp_path, "--backfill", "10", fondo="CFMITNIPSA"), capsys)
    assert _hash(ruta) == antes


def test_ac11_backfill_en_cfinrentas_es_no_op(tmp_path, fuentes, capsys):
    codigo, out, _ = correr(_args(tmp_path, "--backfill", "5"), capsys)
    assert codigo == 0
    assert "[SIN CAMBIOS] CFINRENTAS backfill=no_disponible" in out
    assert not (tmp_path / "quotes" / "CFINRENTAS.backfill.json").exists()


@pytest.mark.parametrize("n", ["0", "156", "-3", "200"])
def test_backfill_fuera_de_rango_es_error_de_configuracion(tmp_path, fuentes, capsys, n):
    codigo, _, err = correr(_args(tmp_path, "--backfill", n), capsys)
    assert codigo == 1
    assert "--backfill" in err


def test_backfill_que_excede_los_puntos_disponibles_no_recorta(tmp_path, fuentes, capsys):
    # Serie de índice recortada a 3 puntos: solo 2 son anteriores al 2026-10-15.
    fuentes["a"] = _indice_corto(fuentes["a"])
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 14), 5054.0853)]),
    )
    antes = ruta.read_bytes()
    codigo, _, err = correr(_args(tmp_path, "--backfill", "30", fondo="CFMITNIPSA"), capsys)
    assert codigo == 1
    assert "no se recorta" in err
    assert ruta.read_bytes() == antes
    assert not (tmp_path / "quotes" / "CFMITNIPSA.backfill.json").exists()


def _indice_corto(html: str) -> str:
    import re

    patron = re.compile(r'\{\\"d\\":\\"(\d{4}-\d{2}-\d{2})\\",\\"v\\":(-?[0-9.eE+-]+)\}')

    def conservar(coincidencia):
        return coincidencia.group(0) if coincidencia.group(1) >= "2026-09-15" else ""

    return patron.sub(conservar, html)


# ── AC-12 ────────────────────────────────────────────────────────────────────


def test_ac12_feed_corrupto_no_se_sobrescribe(tmp_path, fuentes, capsys):
    ruta = tmp_path / "quotes" / "CFINRENTAS.json"
    ruta.parent.mkdir(parents=True)
    original = b'{"ticker": "CFINRENTAS", "data": ['
    ruta.write_bytes(original)

    codigo, out, err = correr(_args(tmp_path, fondo="CFINRENTAS"), capsys)

    assert codigo != 0
    assert "no se pudo leer" in (out + err)
    assert ruta.read_bytes() == original


# ── AC-13 / AC-14 ────────────────────────────────────────────────────────────


def test_ac13_corridas_independientes_generan_bytes_identicos(tmp_path, fuentes, capsys):
    ref = feed_de("CFMITNIPSA", [(date(2026, 10, 14), 5054.0853)])
    escribir_feed(tmp_path / "quotes" / "CFMITNIPSA.json", ref)
    correr(_args(tmp_path, fondo="CFMITNIPSA"), capsys)
    primero = tmp_path / "quotes" / "CFMITNIPSA.json"
    copia = tmp_path / "copia.json"
    copia.write_bytes(primero.read_bytes())

    otra = tmp_path / "otra"
    escribir_feed(otra / "quotes" / "CFMITNIPSA.json", ref)
    correr(
        [
            "--out",
            str(otra / "quotes"),
            "--status-page",
            str(otra / "index.html"),
            "--today",
            HOY,
            "--fondo",
            "CFMITNIPSA",
        ],
        capsys,
    )
    assert _hash(primero) == _hash(otra / "quotes" / "CFMITNIPSA.json")
    assert primero.read_bytes() == copia.read_bytes()


def test_ac14_dry_run_no_escribe_archivos(tmp_path, fuentes, capsys):
    escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 15), 5054.2279)]),
    )
    escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 15), 2181.18)]),
    )
    pagina = tmp_path / "index.html"
    pagina.write_text("anterior", encoding="utf-8")
    hashes = {
        ruta: _hash(ruta)
        for ruta in [
            tmp_path / "quotes" / "CFMITNIPSA.json",
            tmp_path / "quotes" / "CFINRENTAS.json",
            pagina,
        ]
    }

    codigo, _, _ = correr(_args(tmp_path, "--dry-run"), capsys)

    assert codigo == 0
    assert {ruta: _hash(ruta) for ruta in hashes} == hashes


def test_dry_run_no_crea_feeds_nuevos(tmp_path, fuentes, capsys):
    codigo, out, _ = correr(_args(tmp_path, "--dry-run"), capsys)
    assert codigo == 0
    assert "[OK]" in out
    assert not (tmp_path / "quotes").exists()
    assert not (tmp_path / "index.html").exists()


# ── EC-001 / EC-002 / EC-003 / EC-004 ───────────────────────────────────────


def test_ec001_mismo_dia_con_otro_valor_advierte_y_conserva(tmp_path, fuentes, capsys):
    fuentes["a"] = tabla_ledgifi("$5.054,5000", "15 de octubre de 2026")
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 15), 5054.2279)]),
    )

    codigo, out, _ = correr(_args(tmp_path, fondo="CFMITNIPSA"), capsys)

    assert codigo == 0
    assert leer_json(ruta)["data"][-1]["close"] == 5054.2279
    assert "ya existía con otro valor" in out
    assert "5054.5" in out


def test_ec002_fecha_futura_se_rechaza(tmp_path, fuentes, capsys, html_independencia):
    futuro = int(datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp() * 1000)
    fuentes["b"] = html_independencia_con(html_independencia, [[futuro, 2181.18]])
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 14), 2175.45)]),
    )
    antes = ruta.read_bytes()

    codigo, out, _ = correr(_args(tmp_path, fondo="CFINRENTAS"), capsys)

    assert codigo == 3
    assert "fecha implausible" in out
    assert ruta.read_bytes() == antes


def test_ec003_fecha_anterior_es_no_op_informativo(tmp_path, fuentes, capsys):
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 16), 5054.30)]),
    )
    antes = ruta.read_bytes()
    codigo, out, _ = correr(_args(tmp_path, fondo="CFMITNIPSA"), capsys)
    assert codigo == 0
    assert ruta.read_bytes() == antes
    assert "fecha_anterior_al_ultimo_punto" in out


def test_ec004_sin_feed_previo_se_crea(tmp_path, fuentes, capsys):
    codigo, _, _ = correr(_args(tmp_path, fondo="CFMITNIPSA"), capsys)
    datos = leer_json(tmp_path / "quotes" / "CFMITNIPSA.json")
    assert codigo == 0
    assert len(datos["data"]) == 1


# ── Operación ───────────────────────────────────────────────────────────────


def test_genera_la_pagina_de_estado(tmp_path, fuentes, capsys):
    correr(_args(tmp_path), capsys)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "CFMITNIPSA" in html and "CFINRENTAS" in html
    assert "5.054,2279" in html and "2.181,18" in html
    assert "Al día: 2 días hábiles" in html


def test_ticker_desconocido_es_error_de_configuracion(tmp_path, fuentes, capsys):
    codigo, _, err = correr(_args(tmp_path, fondo="CFINEXISTE"), capsys)
    assert codigo == 1
    assert "ticker desconocido" in err


@pytest.mark.parametrize("ticker", ["cfmitnipsa", "CFMITNIPSA.SN", "../evil", ""])
def test_ticker_invalido_es_error_de_configuracion(tmp_path, fuentes, capsys, ticker):
    codigo, _, err = correr(_args(tmp_path, fondo=ticker), capsys)
    assert codigo == 1


def test_today_invalido_es_error_de_configuracion(tmp_path, fuentes, capsys):
    codigo, _, err = correr(
        ["--out", str(tmp_path / "q"), "--today", "19-10-2026"], capsys
    )
    assert codigo == 1
    assert "--today" in err


def test_ruta_con_punto_punto_se_rechaza(tmp_path, fuentes, capsys):
    codigo, _, err = correr(
        ["--out", "../fuera", "--today", HOY], capsys
    )
    assert codigo == 1
    assert ".." in err


def test_escribe_el_resumen_en_github_step_summary(tmp_path, fuentes, capsys, monkeypatch):
    resumen = tmp_path / "resumen.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumen))
    correr(_args(tmp_path), capsys)
    texto = resumen.read_text(encoding="utf-8")
    assert "Feed de cotizaciones" in texto
    assert "CFMITNIPSA" in texto


def test_un_solo_fondo_no_toca_al_otro(tmp_path, fuentes, capsys):
    otro = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 14), 2175.45)]),
    )
    antes = otro.read_bytes()
    correr(_args(tmp_path, fondo="CFMITNIPSA"), capsys)
    assert otro.read_bytes() == antes
    assert (tmp_path / "quotes" / "CFMITNIPSA.json").exists()


def test_all_failed_devuelve_1(tmp_path, fuentes, capsys):
    fuentes["error_a"] = FetchError("sin red")
    fuentes["error_b"] = FetchError("sin red")
    codigo, _, _ = correr(_args(tmp_path), capsys)
    assert codigo == 1
    assert not (tmp_path / "index.html").exists()


def test_all_failed_no_modifica_ningun_archivo(tmp_path, fuentes, capsys):
    """§8: código 1 por "todos los fondos fallaron" deja todo intacto."""

    ruta_a = escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 14), 5054.0853)]),
    )
    ruta_b = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 14), 2175.45)]),
    )
    pagina = tmp_path / "index.html"
    pagina.write_text("anterior", encoding="utf-8")
    hashes = {ruta: _hash(ruta) for ruta in (ruta_a, ruta_b, pagina)}

    fuentes["error_a"] = FetchError("sin red")
    fuentes["error_b"] = FetchError("sin red")
    codigo, _, err = correr(_args(tmp_path), capsys)

    assert codigo == 1
    assert {ruta: _hash(ruta) for ruta in hashes} == hashes
    assert "[FALLA]" in err


@pytest.mark.parametrize("flag", ["--out", "--status-page"])
def test_ruta_fuera_del_repo_se_rechaza(tmp_path, fuentes, capsys, flag):
    """§9: una ruta absoluta fuera de la raíz es error de configuración."""

    destino = Path("/tmp") / f"fund-quotes-fuera-{flag.strip('-')}"
    argumentos = ["--today", HOY]
    argumentos += [flag, str(destino)]

    codigo, _, err = correr(argumentos, capsys)

    assert codigo == 1
    assert "fuera de la raíz" in err
    assert not destino.exists()
