"""REQ-STO-001..004: contrato, determinismo, append-only y protección del feed."""

from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest
from conftest import feed_de, puntos_habiles

from fund_quotes import catalog, store
from fund_quotes.quote import Quote

FUND_A = catalog.get_fund("CFMITNIPSA")
FUND_B = catalog.get_fund("CFINRENTAS")


def _hash(ruta) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def test_ac13_serializacion_determinista_y_orden_de_claves(tmp_path):
    feed = feed_de("CFMITNIPSA", [(date(2026, 10, 14), 5054.0853), (date(2026, 10, 15), 5054.2279)])
    primera = store.serialize(feed)
    segunda = store.serialize(feed)
    assert primera == segunda
    assert hashlib.sha256(primera).hexdigest() == hashlib.sha256(segunda).hexdigest()

    texto = primera.decode("utf-8")
    claves = list(json.loads(texto).keys())
    assert claves == ["ticker", "name", "currency", "source", "updated", "data"]
    assert texto.index('"ticker"') < texto.index('"name"') < texto.index('"currency"')
    assert texto.index('"currency"') < texto.index('"source"') < texto.index('"updated"')
    assert texto.index('"updated"') < texto.index('"data"')


def test_ac13_formato_indent_utf8_sin_bom_y_newline_final(tmp_path):
    feed = feed_de("CFINRENTAS", [(date(2026, 10, 15), 2181.18)])
    crudo = store.serialize(feed)
    assert not crudo.startswith(b"\xef\xbb\xbf")
    assert crudo.endswith(b"\n")
    texto = crudo.decode("utf-8")
    assert '\n  "ticker": "CFINRENTAS"' in texto
    assert "\n    {\n      \"date\": \"2026-10-15\",\n      \"close\": 2181.18\n    }\n" in texto


def test_ac13_dos_escrituras_producen_el_mismo_hash(tmp_path):
    feed = feed_de("CFMITNIPSA", [(date(2026, 10, 15), 5054.2279)])
    ruta_a = tmp_path / "a" / "CFMITNIPSA.json"
    ruta_b = tmp_path / "b" / "CFMITNIPSA.json"
    store.write_feed(ruta_a, feed)
    store.write_feed(ruta_b, feed)
    assert _hash(ruta_a) == _hash(ruta_b)


def test_ac13_el_contrato_incluye_currency_clp_y_name_del_catalogo():
    feed = feed_de("CFMITNIPSA", [(date(2026, 10, 15), 5054.2279)])
    datos = json.loads(store.serialize(feed))
    assert datos["currency"] == "CLP"
    assert datos["name"] == "FM IT NOW S&P IPSA"
    assert datos["source"] == "dividendera:CFMITNIPSA"
    assert datos["updated"] == "2026-10-15"
    assert datos["data"] == [{"date": "2026-10-15", "close": 5054.2279}]


def test_lee_un_feed_valido(tmp_path):
    feed = feed_de("CFMITNIPSA", [(date(2026, 10, 15), 5054.2279)])
    ruta = tmp_path / "CFMITNIPSA.json"
    store.write_feed(ruta, feed)
    leido = store.read_feed(ruta, FUND_A)
    assert leido is not None
    assert leido.last == Quote(date(2026, 10, 15), 5054.2279)


def test_sin_archivo_devuelve_none(tmp_path):
    assert store.read_feed(tmp_path / "no-existe.json", FUND_A) is None


@pytest.mark.parametrize(
    "contenido",
    [
        "{no es json",
        "[]",
        '{"ticker":"CFMITNIPSA"}',
        "",
    ],
)
def test_ac12_feed_corrupto_no_se_lee(tmp_path, contenido):
    ruta = tmp_path / "CFMITNIPSA.json"
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(store.FeedError) as excinfo:
        store.read_feed(ruta, FUND_A)
    assert "no se pudo leer" in str(excinfo.value)
    assert ruta.read_text(encoding="utf-8") == contenido


@pytest.mark.parametrize(
    ("campo", "valor", "motivo"),
    [
        ("ticker", "OTRO", "ticker"),
        ("currency", "USD", "currency"),
        ("updated", "2026-10-14", "updated"),
    ],
)
def test_rechaza_contrato_invalido(tmp_path, campo, valor, motivo):
    feed = feed_de("CFMITNIPSA", [(date(2026, 10, 14), 5054.0), (date(2026, 10, 15), 5054.2279)])
    datos = json.loads(store.serialize(feed))
    datos[campo] = valor
    ruta = tmp_path / "CFMITNIPSA.json"
    ruta.write_text(json.dumps(datos, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(store.FeedError) as excinfo:
        store.read_feed(ruta, FUND_A)
    assert "no se pudo leer" in str(excinfo.value)


def test_rechaza_fechas_desordenadas_o_duplicadas(tmp_path):
    datos = {
        "ticker": "CFMITNIPSA",
        "name": "FM IT NOW S&P IPSA",
        "currency": "CLP",
        "source": "ledgifi:9019",
        "updated": "2026-10-14",
        "data": [
            {"date": "2026-10-15", "close": 5054.2279},
            {"date": "2026-10-14", "close": 5054.0853},
        ],
    }
    ruta = tmp_path / "CFMITNIPSA.json"
    ruta.write_text(json.dumps(datos) + "\n", encoding="utf-8")
    with pytest.raises(store.FeedError):
        store.read_feed(ruta, FUND_A)

    datos["data"] = [
        {"date": "2026-10-14", "close": 5054.0853},
        {"date": "2026-10-14", "close": 5054.0853},
    ]
    datos["updated"] = "2026-10-14"
    ruta.write_text(json.dumps(datos) + "\n", encoding="utf-8")
    with pytest.raises(store.FeedError):
        store.read_feed(ruta, FUND_A)


def test_rechaza_close_como_texto(tmp_path):
    datos = {
        "ticker": "CFMITNIPSA",
        "name": "FM IT NOW S&P IPSA",
        "currency": "CLP",
        "source": "ledgifi:9019",
        "updated": "2026-10-15",
        "data": [{"date": "2026-10-15", "close": "5054.2279"}],
    }
    ruta = tmp_path / "CFMITNIPSA.json"
    ruta.write_text(json.dumps(datos) + "\n", encoding="utf-8")
    with pytest.raises(store.FeedError):
        store.read_feed(ruta, FUND_A)


def test_ec004_sin_feed_previo_se_crea_con_un_punto():
    quote = Quote(date(2026, 10, 15), 2181.18)
    resultado = store.merge(None, quote, FUND_B)
    assert resultado.estado == "nuevo"
    assert resultado.feed.data == [quote]
    assert resultado.feed.updated == date(2026, 10, 15)
    assert resultado.agregados == [quote]


def test_ac03_append_only_conserva_los_100_puntos_previos():
    previos = puntos_habiles(100, date(2026, 10, 14), 2175.45)
    feed = feed_de("CFINRENTAS", previos)
    nuevo = Quote(date(2026, 10, 15), 2181.18)
    resultado = store.merge(feed, nuevo, FUND_B)
    assert resultado.estado == "agregado"
    assert resultado.agregados == [nuevo]
    assert len(resultado.feed.data) == 101
    assert resultado.feed.data[:100] == feed.data
    assert resultado.feed.data[-1] == nuevo
    assert resultado.feed.updated == date(2026, 10, 15)


def test_ac02_idempotencia_no_cambia_el_feed():
    feed = feed_de("CFMITNIPSA", [(date(2026, 10, 15), 5054.2279)])
    antes = store.serialize(feed)
    resultado = store.merge(feed, Quote(date(2026, 10, 15), 5054.2279), FUND_A)
    assert resultado.estado == "sin_cambios"
    assert store.serialize(resultado.feed) == antes


def test_ec001_mismo_dia_con_otro_valor_conserva_el_guardado():
    feed = feed_de("CFMITNIPSA", [(date(2026, 10, 15), 5054.2279)])
    resultado = store.merge(feed, Quote(date(2026, 10, 15), 5054.50), FUND_A)
    assert resultado.estado == "conflicto"
    assert resultado.feed.data == feed.data


def test_ec003_fecha_anterior_al_ultimo_punto_es_no_op():
    feed = feed_de("CFMITNIPSA", [(date(2026, 10, 14), 5054.0853), (date(2026, 10, 15), 5054.2279)])
    resultado = store.merge(feed, Quote(date(2026, 10, 13), 5000.0), FUND_A)
    assert resultado.estado == "antiguo"
    assert resultado.feed.data == feed.data


def test_ec008_falla_de_escritura_deja_el_original_intacto(tmp_path, monkeypatch):
    ruta = tmp_path / "CFMITNIPSA.json"
    original = b'{"ticker": "CFMITNIPSA"}\n'
    ruta.write_bytes(original)

    def falla(*args, **kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(store.os, "replace", falla)
    feed = feed_de("CFMITNIPSA", [(date(2026, 10, 15), 5054.2279)])
    with pytest.raises(store.FeedError):
        store.write_feed(ruta, feed)
    assert ruta.read_bytes() == original
    assert list(tmp_path.iterdir()) == [ruta]


def test_escritura_atomica_reemplaza_el_archivo(tmp_path):
    ruta = tmp_path / "CFMITNIPSA.json"
    ruta.write_text("viejo", encoding="utf-8")
    store.write_atomic(ruta, b"nuevo\n")
    assert ruta.read_bytes() == b"nuevo\n"
