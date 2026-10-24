"""Fixtures y utilidades comunes. Ninguna prueba abre conexiones de red."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from fund_quotes import catalog, store
from fund_quotes.quote import Quote

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def html_ledgifi() -> str:
    return (FIXTURES / "ledgifi_9019.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def html_independencia() -> str:
    return (FIXTURES / "aindependencia_fondos.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def md_ledgifi() -> str:
    """Recorte verbatim del modo markdown de r.jina.ai (fila UNICA del 2026-10-22)."""

    return (FIXTURES / "ledgifi_9019.md").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def raiz_repo_temporal(tmp_path, monkeypatch):
    """Autoriza ``tmp_path`` como raíz del repo: los tests escriben ahí (§9)."""

    from fund_quotes import cli

    monkeypatch.setattr(cli, "RAIZ_REPO", tmp_path)
    return tmp_path


@pytest.fixture
def fuentes(monkeypatch, html_ledgifi, html_independencia):
    """Reemplaza la descarga real por los fixtures guardados."""

    from fund_quotes.sources import aindependencia, ledgifi

    estado = {
        "a": html_ledgifi,
        "b": html_independencia,
        "error_a": None,
        "error_b": None,
        "llamadas_a": 0,
        "llamadas_b": 0,
    }

    def falso_a(*args, **kwargs):
        estado["llamadas_a"] += 1
        if estado["error_a"] is not None:
            raise estado["error_a"]
        return estado["a"]

    def falso_b(*args, **kwargs):
        estado["llamadas_b"] += 1
        if estado["error_b"] is not None:
            raise estado["error_b"]
        return estado["b"]

    monkeypatch.setattr(ledgifi, "fetch_text", falso_a)
    monkeypatch.setattr(aindependencia, "fetch_text", falso_b)
    return estado


def tabla_ledgifi(
    valor: str = "$5.054,2279",
    fecha: str = "15 de octubre de 2026",
    serie: str = "UNICA",
) -> str:
    """HTML con la misma estructura de celdas que la tabla real de LedgiFi."""

    return (
        "<html><body><table>"
        "<thead><tr><th>Serie</th><th>Rentabilidad 1 año</th>"
        "<th>Valor cuota</th></tr></thead><tbody><tr>"
        f'<td><span class="font-mono">{serie}</span>'
        "<span>condición no publicada</span></td>"
        "<td><span>15,7%</span></td>"
        f'<td><span><span class="sr-only">{valor}</span>'
        f'<span aria-hidden="true">{valor}</span></span>'
        f'<span class="block text-xs">{fecha}</span></td>'
        "</tr></tbody></table></body></html>"
    )


def puntos_habiles(n: int, fin: date, cierre: float) -> list[tuple[date, float]]:
    """``n`` días hábiles ascendentes terminando en ``fin``."""

    puntos: list[tuple[date, float]] = []
    cursor = fin
    while len(puntos) < n:
        if cursor.weekday() < 5:
            puntos.append((cursor, cierre))
        cursor -= timedelta(days=1)
    return list(reversed(puntos))


def feed_de(
    ticker: str,
    puntos: list[tuple[date, float]],
    *,
    source: str | None = None,
    name: str | None = None,
) -> store.Feed:
    fund = catalog.get_fund(ticker)
    return store.Feed(
        ticker=ticker,
        name=name or fund.name,
        currency="CLP",
        source=source or fund.source,
        updated=puntos[-1][0],
        data=[Quote(date=fecha, close=cierre) for fecha, cierre in puntos],
    )


def escribir_feed(ruta: Path, feed: store.Feed) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    store.write_feed(ruta, feed)
    return ruta


def leer_json(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def correr(args: list[str], capsys) -> tuple[int, str, str]:
    from fund_quotes import cli

    codigo = cli.main(args)
    capturado = capsys.readouterr()
    return codigo, capturado.out, capturado.err


def html_independencia_con(html: str, puntos_bolsa: list[list[float]]) -> str:
    """Reescribe la serie BOLSA del fixture con los pares indicados."""

    from fund_quotes.sources import aindependencia

    datos = aindependencia.extraer_chart_data(html)
    for serie in datos["series"]:
        if serie["name"].strip().upper() == "BOLSA":
            serie["data"] = puntos_bolsa
    bloque = json.dumps(datos, separators=(",", ":"), ensure_ascii=False)
    inicio = html.find("var vfiChartData")
    fin = html.find(";\n", inicio)
    return html[:inicio] + "var vfiChartData = " + bloque + html[fin:]
