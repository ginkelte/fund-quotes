"""Fuente B — Independencia, serie BOLSA (CFINRENTAS, RUN 7014-9).

El sitio entrega HTML plano con un objeto JSON embebido. Se extrae el objeto
balanceando llaves y se pasa por ``json.loads``; nunca se evalúa JavaScript.
La fecha se deriva del epoch en UTC (no en hora de Chile), según §4.2.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from ..fetch import fetch_text
from ..quote import Quote, QuoteFormatError, close_desde_decimal
from . import SourceError

URL = "https://www.aindependencia.cl/fondos/"
FUENTE = "aindependencia:bolsa"
SERIE = "BOLSA"
MARCADOR = "vfiChartData"


def extraer_chart_data(html: str) -> dict:
    """Extrae ``window.vfiChartData = {...}`` balanceando llaves, sin eval."""

    if not isinstance(html, str) or not html:
        raise SourceError("la respuesta de Independencia está vacía")
    posicion = html.find(MARCADOR)
    if posicion < 0:
        raise SourceError(
            "no se encontró la serie BOLSA: la página de Independencia no trae "
            f"'{MARCADOR}' (posible rediseño del sitio)"
        )
    inicio = html.find("{", posicion)
    if inicio < 0:
        raise SourceError(f"'{MARCADOR}' no viene seguido de un objeto JSON")

    profundidad = 0
    en_texto = False
    escape = False
    fin = -1
    for indice in range(inicio, len(html)):
        caracter = html[indice]
        if en_texto:
            if escape:
                escape = False
            elif caracter == "\\":
                escape = True
            elif caracter == '"':
                en_texto = False
            continue
        if caracter == '"':
            en_texto = True
        elif caracter == "{":
            profundidad += 1
        elif caracter == "}":
            profundidad -= 1
            if profundidad == 0:
                fin = indice + 1
                break

    if fin < 0:
        raise SourceError(f"el objeto '{MARCADOR}' está truncado: no se pudo balancear")

    try:
        datos = json.loads(html[inicio:fin])
    except ValueError as exc:
        raise SourceError(f"el objeto '{MARCADOR}' no es JSON válido: {exc}") from None
    if not isinstance(datos, dict):
        raise SourceError(f"'{MARCADOR}' no es un objeto JSON")
    return datos


def _serie_bolsa(datos: dict) -> list:
    series = datos.get("series")
    if not isinstance(series, list):
        raise SourceError("no se encontró la serie BOLSA: el objeto no trae 'series'")
    for serie in series:
        if not isinstance(serie, dict):
            continue
        nombre = serie.get("name")
        if isinstance(nombre, str) and nombre.strip().upper() == SERIE:
            puntos = serie.get("data")
            if not isinstance(puntos, list) or not puntos:
                raise SourceError("la serie BOLSA no trae datos")
            return puntos
    disponibles = ", ".join(
        str(serie.get("name")) for serie in series if isinstance(serie, dict)
    )
    raise SourceError(
        f"no se encontró la serie BOLSA en la página de Independencia "
        f"(series disponibles: {disponibles or 'ninguna'})"
    )


def _epoch_a_ms(epoch_ms: float) -> int:
    """Convierte el epoch en milisegundos; ``NaN``/``Infinity`` no pasan."""

    try:
        return int(epoch_ms)
    except (ValueError, OverflowError) as exc:
        raise SourceError(f"la serie BOLSA trae un epoch inválido: {epoch_ms!r}") from exc


def _fecha_desde_ms(ms: int) -> date:
    """Fecha UTC del epoch en milisegundos, con rango acotado por ``datetime``."""

    try:
        return datetime.fromtimestamp(ms / 1000, tz=UTC).date()
    except (ValueError, OverflowError, OSError) as exc:
        raise SourceError(f"la serie BOLSA trae un epoch inválido: {ms!r}") from exc


def parse_quote(html: str) -> Quote:
    """Toma el punto de mayor ``epoch_ms`` de la serie BOLSA (fecha en UTC)."""

    datos = extraer_chart_data(html)
    puntos = _serie_bolsa(datos)

    mejor_ms: int | None = None
    mejor_valor: Decimal | None = None
    for punto in puntos:
        if not isinstance(punto, (list, tuple)) or len(punto) < 2:
            continue
        epoch_ms, valor = punto[0], punto[1]
        if isinstance(epoch_ms, bool) or not isinstance(epoch_ms, (int, float)):
            continue
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            continue
        try:
            decimal = Decimal(str(float(valor)))
        except InvalidOperation:
            continue
        if not decimal.is_finite() or decimal <= 0:
            continue
        ms = _epoch_a_ms(epoch_ms)
        if mejor_ms is None or ms > mejor_ms:
            mejor_ms = ms
            mejor_valor = decimal

    if mejor_ms is None or mejor_valor is None:
        raise SourceError("la serie BOLSA no tiene puntos numéricos utilizables")

    fecha = _fecha_desde_ms(mejor_ms)
    try:
        cierre = close_desde_decimal(mejor_valor)
    except QuoteFormatError as exc:
        raise SourceError(f"el cierre de la serie BOLSA no es válido: {exc}") from None
    return Quote(date=fecha, close=cierre)


def cargar(con_indice: bool = False) -> tuple[Quote, None]:
    """Una sola petición a la fuente. Esta fuente no expone serie de índice."""

    html = fetch_text(URL, min_bytes=10_000)
    return parse_quote(html), None
