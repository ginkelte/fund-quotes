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


@pytest.fixture(scope="session")
def html_dividendera_cfinrentas() -> str:
    """Recorte verbatim de https://www.dividendera.cl/CFINRENTAS (2026-10-22)."""

    return (FIXTURES / "dividendera_CFINRENTAS.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def html_dividendera_cfmitnipsa() -> str:
    """Recorte verbatim de https://www.dividendera.cl/CFMITNIPSA (2026-10-23)."""

    return (FIXTURES / "dividendera_CFMITNIPSA.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def raiz_repo_temporal(tmp_path, monkeypatch):
    """Autoriza ``tmp_path`` como raíz del repo: los tests escriben ahí (§9)."""

    from fund_quotes import cli

    monkeypatch.setattr(cli, "RAIZ_REPO", tmp_path)
    return tmp_path


@pytest.fixture
def fuentes(monkeypatch, html_ledgifi, html_independencia):
    """Reemplaza la descarga real por los fixtures guardados.

    ``d`` es dividendera, la primaria de CFINRENTAS: por defecto **falla** para que
    las pruebas anteriores a su incorporación sigan ejercitando el camino de
    respaldo (aindependencia). Las pruebas que quieren la primaria hacen
    ``fuentes["error_d"] = None`` y ``fuentes["d"] = <fixture>``.
    """

    from fund_quotes.fetch import FetchError
    from fund_quotes.sources import aindependencia, dividendera, ledgifi

    estado = {
        "a": html_ledgifi,
        "b": html_independencia,
        "d": None,
        "error_a": None,
        "error_b": None,
        "error_d": FetchError(
            "dividendera: fuente no habilitada en esta prueba (se usa el respaldo)"
        ),
        "llamadas_a": 0,
        "llamadas_b": 0,
        "llamadas_d": 0,
        "urls_d": [],
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

    def falso_d(url, *args, **kwargs):
        estado["llamadas_d"] += 1
        estado["urls_d"].append(url)
        if estado["error_d"] is not None:
            raise estado["error_d"]
        assert estado["d"] is not None, "falta el fixture de dividendera"
        return estado["d"]

    monkeypatch.setattr(ledgifi, "fetch_text", falso_a)
    monkeypatch.setattr(aindependencia, "fetch_text", falso_b)
    monkeypatch.setattr(dividendera, "fetch_text", falso_d)
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


def html_dividendera_con(
    puntos: list[tuple[str, float]], nemo: str = "CFINRENTAS"
) -> str:
    """Página sintética de dividendera con la serie indicada (mismo payload real).

    Los objetos van con las comillas escapadas, como en el chunk de Next.js, y se
    rellena hasta pasar el piso de tamaño del adaptador.
    """

    from fund_quotes.sources import dividendera

    objetos = ",".join(
        f'{{\\"id\\":{posicion},\\"nemo\\":\\"{nemo}\\",'
        f'\\"fecha\\":\\"$D{fecha}T00:00:00.000Z\\",'
        f'\\"cierre\\":{cierre},\\"volumen\\":1000}}'
        for posicion, (fecha, cierre) in enumerate(puntos)
    )
    cuerpo = '<script>self.__next_f.push([1,"[' + objetos + ']"])</script>'
    relleno = " " * max(0, dividendera.MIN_BYTES - len(cuerpo) + 1024)
    return "<html><body>" + cuerpo + relleno + "</body></html>"
