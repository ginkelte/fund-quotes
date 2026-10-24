"""AC-15 (catch-up multi-punto) y AC-16 (siembra de historia), sin red.

Todo se ejercita con fixtures: la página de dividendera se arma con el mismo
formato de payload que la ficha real (``conftest.html_dividendera_con``).
"""

from __future__ import annotations

import hashlib
from datetime import date

import pytest
from conftest import (
    correr,
    escribir_feed,
    feed_de,
    html_dividendera_con,
    leer_json,
)

from fund_quotes import catalog, store
from fund_quotes.quote import Quote

# Serie diaria de CFINRENTAS alrededor del hueco de octubre (cierre BCS).
SERIE = [
    ("2026-10-13", 2172.4),
    ("2026-10-14", 2175.45),
    ("2026-10-15", 2181.18),
    ("2026-10-16", 2170.5),
    ("2026-10-19", 2169.08),
    ("2026-10-20", 2175.022),
    ("2026-10-21", 2180.953),
    ("2026-10-22", 2181.73),
]


def _hash(ruta) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


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


# ── AC-15: catch-up multi-punto ──────────────────────────────────────────────


def test_ac15_feed_con_3_puntos_y_fuente_con_5_quedan_5(tmp_path, fuentes, capsys):
    """El feed tenía un punto por corrida; ahora entra todo el tramo que falte."""

    fuente = SERIE[0:5]  # 13, 14, 15, 16 y 19 de octubre
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_con(fuente)
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de(
            "CFINRENTAS",
            [
                (date(2026, 10, 13), 2172.4),
                (date(2026, 10, 14), 2175.45),
                (date(2026, 10, 15), 2181.18),
            ],
        ),
    )

    codigo, out, err = correr(_args(tmp_path, "2026-10-19", fondo="CFINRENTAS"), capsys)

    datos = leer_json(ruta)
    fechas = [punto["date"] for punto in datos["data"]]
    assert codigo == 0
    assert err == ""
    assert len(datos["data"]) == 5
    assert fechas == ["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19"]
    assert fechas == sorted(fechas)
    assert len(fechas) == len(set(fechas))
    assert datos["updated"] == "2026-10-19"
    assert datos["data"][-1] == {"date": "2026-10-19", "close": 2169.08}
    assert (
        "[OK] CFINRENTAS fecha=2026-10-19 close=2169.08 "
        "fuente=dividendera:CFINRENTAS nuevos=2" in out
    )


def test_ac15_segunda_corrida_con_la_misma_serie_no_cambia_nada(tmp_path, fuentes, capsys):
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_con(SERIE[2:7])
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 15), 2181.18)]),
    )
    correr(_args(tmp_path, "2026-10-21", fondo="CFINRENTAS"), capsys)
    antes = _hash(ruta)

    codigo, out, _ = correr(_args(tmp_path, "2026-10-21", fondo="CFINRENTAS"), capsys)

    assert codigo == 0
    assert _hash(ruta) == antes
    assert "[SIN CAMBIOS] CFINRENTAS" in out
    assert "motivo=ya_publicado" in out


def test_ac15_la_serie_completa_no_duplica_fechas_ni_reordena(tmp_path, fuentes, capsys):
    """La fuente trae toda la historia: solo se agrega lo posterior al último punto."""

    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_con(SERIE)
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de(
            "CFINRENTAS",
            [(date(2026, 10, 13), 2172.4), (date(2026, 10, 14), 2175.45)],
        ),
    )

    codigo, out, _ = correr(_args(tmp_path, "2026-10-22", fondo="CFINRENTAS"), capsys)

    datos = leer_json(ruta)
    fechas = [punto["date"] for punto in datos["data"]]
    assert codigo == 0
    assert fechas == [fecha for fecha, _ in SERIE]
    assert datos["data"][:2] == [
        {"date": "2026-10-13", "close": 2172.4},
        {"date": "2026-10-14", "close": 2175.45},
    ]
    assert "nuevos=6" in out


def test_fuente_de_un_solo_punto_sigue_funcionando(tmp_path, fuentes, capsys):
    """LedgiFi solo publica el último valor: el contrato multi-punto no lo rompe."""

    ruta = escribir_feed(
        tmp_path / "quotes" / "CFMITNIPSA.json",
        feed_de("CFMITNIPSA", [(date(2026, 10, 14), 5054.0853)]),
    )

    codigo, out, _ = correr(_args(tmp_path, "2026-10-19", fondo="CFMITNIPSA"), capsys)

    datos = leer_json(ruta)
    assert codigo == 0
    assert datos["data"][-1] == {"date": "2026-10-15", "close": 5054.2279}
    assert datos["source"] == "ledgifi:9019"
    assert "nuevos=1" in out


def test_punto_intermedio_con_salto_mayor_al_umbral_se_rechaza_solo_ese(
    tmp_path, fuentes, capsys
):
    """La guarda es punto a punto: el pico se descarta, el resto del tramo entra."""

    fuente = [
        ("2026-10-15", 2181.18),
        ("2026-10-16", 2400.0),  # +10,03%: se rechaza
        ("2026-10-19", 2185.0),  # +0,18% contra el último aceptado
    ]
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_con(fuente)
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 14), 2175.45)]),
    )

    codigo, out, _ = correr(_args(tmp_path, "2026-10-19", fondo="CFINRENTAS"), capsys)

    datos = leer_json(ruta)
    assert codigo == 3
    assert [punto["date"] for punto in datos["data"]] == [
        "2026-10-14",
        "2026-10-15",
        "2026-10-19",
    ]
    assert datos["updated"] == "2026-10-19"
    assert "[ANOMALIA] CFINRENTAS" in out
    assert "fecha=2026-10-16" in out
    assert "+10,03%" in out
    assert "[OK] CFINRENTAS fecha=2026-10-19" in out and "nuevos=2" in out


def test_el_pico_rechazado_no_corta_el_resto_de_la_serie(tmp_path, fuentes, capsys):
    fuente = [
        ("2026-10-15", 2181.18),
        ("2026-10-16", 2400.0),  # rechazado
        ("2026-10-19", 2170.0),
        ("2026-10-20", 2175.0),
        ("2026-10-21", 2180.0),
    ]
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_con(fuente)
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 14), 2175.45)]),
    )

    codigo, out, _ = correr(_args(tmp_path, "2026-10-21", fondo="CFINRENTAS"), capsys)

    fechas = [punto["date"] for punto in leer_json(ruta)["data"]]
    assert codigo == 3
    assert fechas == ["2026-10-14", "2026-10-15", "2026-10-19", "2026-10-20", "2026-10-21"]
    assert out.count("[ANOMALIA] CFINRENTAS") == 1
    assert "nuevos=4" in out


def test_force_anomaly_acepta_tambien_el_punto_intermedio(tmp_path, fuentes, capsys):
    fuente = [("2026-10-15", 2181.18), ("2026-10-16", 2400.0), ("2026-10-19", 2405.0)]
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_con(fuente)
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 14), 2175.45)]),
    )

    codigo, out, _ = correr(
        _args(tmp_path, "2026-10-19", "--force-anomaly", fondo="CFINRENTAS"), capsys
    )

    datos = leer_json(ruta)
    assert codigo == 0
    assert len(datos["data"]) == 4
    assert "forzada" in out


# ── AC-16: siembra de historia ───────────────────────────────────────────────


def test_ac16_siembra_los_ultimos_n_dias_habiles_en_un_feed_inexistente(
    tmp_path, fuentes, capsys
):
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_con(SERIE)

    codigo, out, err = correr(
        _args(tmp_path, "2026-10-24", "--sembrar-historia", "3", fondo="CFINRENTAS"),
        capsys,
    )

    datos = leer_json(tmp_path / "quotes" / "CFINRENTAS.json")
    assert codigo == 0
    assert err == ""
    assert len(datos["data"]) == 3
    assert [punto["date"] for punto in datos["data"]] == [
        "2026-10-20",
        "2026-10-21",
        "2026-10-22",
    ]
    assert datos["updated"] == "2026-10-22"
    assert datos["source"] == "dividendera:CFINRENTAS"
    assert "nuevos=3" in out and "siembra de historia" in out


def test_ac16_la_siembra_no_aplica_la_guarda_de_anomalia(tmp_path, fuentes, capsys):
    """Son cierres oficiales ya publicados: un salto >5% no se rechaza."""

    fuente = [
        ("2026-10-14", 1800.0),
        ("2026-10-15", 2181.18),  # +21%: historia oficial, no se filtra
        ("2026-10-16", 2170.5),
        ("2026-10-19", 2169.08),
        ("2026-10-20", 2175.022),
    ]
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_con(fuente)

    codigo, out, _ = correr(
        _args(tmp_path, "2026-10-21", "--sembrar-historia", "5", fondo="CFINRENTAS"),
        capsys,
    )

    datos = leer_json(tmp_path / "quotes" / "CFINRENTAS.json")
    assert codigo == 0
    assert len(datos["data"]) == 5
    assert "[ANOMALIA]" not in out


def test_ac16_siembra_solo_dias_habiles_y_salta_el_fin_de_semana(tmp_path, fuentes, capsys):
    fuente = [
        ("2026-10-16", 2170.5),  # viernes
        ("2026-10-17", 9999.0),  # sábado: no entra
        ("2026-10-19", 2169.08),  # lunes
    ]
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_con(fuente)

    codigo, _, _ = correr(
        _args(tmp_path, "2026-10-20", "--sembrar-historia", "2", fondo="CFINRENTAS"),
        capsys,
    )

    datos = leer_json(tmp_path / "quotes" / "CFINRENTAS.json")
    assert codigo == 0
    assert [punto["date"] for punto in datos["data"]] == ["2026-10-16", "2026-10-19"]


def test_ac16_siembra_con_feed_existente_es_no_op_con_aviso(tmp_path, fuentes, capsys):
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_con(SERIE)
    ruta = escribir_feed(
        tmp_path / "quotes" / "CFINRENTAS.json",
        feed_de("CFINRENTAS", [(date(2026, 10, 22), 2181.73)]),
    )
    antes = _hash(ruta)

    codigo, out, _ = correr(
        _args(tmp_path, "2026-10-22", "--sembrar-historia", "120", fondo="CFINRENTAS"),
        capsys,
    )

    assert codigo == 0
    assert _hash(ruta) == antes
    assert (
        "[AVISO] CFINRENTAS --sembrar-historia no se aplica: el feed ya existe "
        "con 1 puntos" in out
    )
    assert "[SIN CAMBIOS] CFINRENTAS" in out


def test_ac16_siembra_recorta_a_lo_disponible_y_avisa(tmp_path, fuentes, capsys):
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_con(SERIE[-2:])

    codigo, out, _ = correr(
        _args(tmp_path, "2026-10-24", "--sembrar-historia", "120", fondo="CFINRENTAS"),
        capsys,
    )

    datos = leer_json(tmp_path / "quotes" / "CFINRENTAS.json")
    assert codigo == 0
    assert len(datos["data"]) == 2
    assert "se sembró todo lo disponible" in out


@pytest.mark.parametrize("n", ["0", "801", "-5", "1000"])
def test_sembrar_historia_fuera_de_rango_es_error_de_configuracion(
    tmp_path, fuentes, capsys, n
):
    codigo, _, err = correr(_args(tmp_path, "2026-10-22", "--sembrar-historia", n), capsys)
    assert codigo == 1
    assert "--sembrar-historia" in err
    assert not (tmp_path / "quotes").exists()


def test_sembrar_historia_en_dry_run_no_escribe(tmp_path, fuentes, capsys):
    fuentes["error_d"] = None
    fuentes["d"] = html_dividendera_con(SERIE)

    codigo, out, _ = correr(
        _args(
            tmp_path,
            "2026-10-24",
            "--sembrar-historia",
            "3",
            "--dry-run",
            fondo="CFINRENTAS",
        ),
        capsys,
    )

    assert codigo == 0
    assert "nuevos=3" in out
    assert not (tmp_path / "quotes").exists()


# ── Store: merge multi-punto y siembra ───────────────────────────────────────

FUND_B = catalog.get_fund("CFINRENTAS")


def _quote(fecha: str, cierre: float) -> Quote:
    return Quote(date.fromisoformat(fecha), cierre)


def test_store_merge_agrega_todos_los_puntos_posteriores():
    feed = feed_de(
        "CFINRENTAS",
        [(date(2026, 10, 15), 2181.18), (date(2026, 10, 19), 2169.08), (date(2026, 10, 20), 2175.022)],
    )
    nuevos = [_quote(fecha, cierre) for fecha, cierre in SERIE[2:7]]

    resultado = store.merge(feed, nuevos, FUND_B)

    # Append-only: el 16-10 quedó antes del último publicado (20-10) y no se
    # reescribe la historia; el catch-up agrega solo lo posterior.
    assert resultado.estado == "agregado"
    assert [punto.date.isoformat() for punto in resultado.agregados] == ["2026-10-21"]
    assert [punto.date.isoformat() for punto in resultado.feed.data] == [
        "2026-10-15",
        "2026-10-19",
        "2026-10-20",
        "2026-10-21",
    ]
    assert resultado.feed.updated == date(2026, 10, 21)


def test_store_merge_descarta_duplicados_y_anteriores():
    feed = feed_de(
        "CFINRENTAS",
        [(date(2026, 10, 20), 2175.022), (date(2026, 10, 21), 2180.953)],
    )
    nuevos = [_quote(fecha, cierre) for fecha, cierre in SERIE]

    resultado = store.merge(feed, nuevos, FUND_B)

    assert [punto.date.isoformat() for punto in resultado.feed.data] == [
        "2026-10-20",
        "2026-10-21",
        "2026-10-22",
    ]
    assert [punto.date.isoformat() for punto in resultado.descartados] == [
        "2026-10-13",
        "2026-10-14",
        "2026-10-15",
        "2026-10-16",
        "2026-10-19",
        "2026-10-20",
        "2026-10-21",
    ]


def test_store_merge_de_una_serie_completa_en_feed_vacio_ordena_y_deduplica():
    desordenada = [
        _quote("2026-10-21", 2180.953),
        _quote("2026-10-19", 2169.08),
        _quote("2026-10-21", 2180.953),
        _quote("2026-10-20", 2175.022),
    ]

    resultado = store.merge(None, desordenada, FUND_B)

    assert resultado.estado == "nuevo"
    assert [punto.date.isoformat() for punto in resultado.feed.data] == [
        "2026-10-19",
        "2026-10-20",
        "2026-10-21",
    ]
    assert resultado.feed.updated == date(2026, 10, 21)


def test_store_sembrar_toma_los_ultimos_n_habiles():
    serie = [_quote(fecha, cierre) for fecha, cierre in SERIE]

    feed = store.sembrar(FUND_B, serie, 4, source="dividendera:CFINRENTAS")

    assert [punto.date.isoformat() for punto in feed.data] == [
        "2026-10-19",
        "2026-10-20",
        "2026-10-21",
        "2026-10-22",
    ]
    assert feed.updated == date(2026, 10, 22)
    assert feed.source == "dividendera:CFINRENTAS"


def test_store_sembrar_no_aplica_la_guarda_de_anomalia():
    serie = [_quote("2026-10-15", 1800.0), _quote("2026-10-16", 2181.73)]

    feed = store.sembrar(FUND_B, serie, 2)

    assert len(feed.data) == 2


def test_determinismo_con_serie_larga():
    """Dos serializaciones del mismo feed multi-punto son idénticas byte a byte."""

    feed = store.sembrar(FUND_B, [_quote(fecha, cierre) for fecha, cierre in SERIE], 6)
    primera = store.serialize(feed)
    segunda = store.serialize(feed)
    assert primera == segunda
    assert hashlib.sha256(primera).digest() == hashlib.sha256(segunda).digest()
    assert primera.endswith(b"\n")
