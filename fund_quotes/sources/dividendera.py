"""Fuente C — Dividendera (CFINRENTAS primaria; respaldo de CFMITNIPSA).

``https://www.dividendera.cl/<NEMO>`` es una app Next.js que responde HTTP 200
directo (sin proxy ni captcha) y embebe los cierres diarios de la Bolsa de
Santiago en los chunks ``self.__next_f.push([1,"..."])``. Cada punto es un objeto
``{"id":…,"nemo":…,"fecha":"$D<YYYY-MM-DD>T00:00:00.000Z","cierre":…,"volumen":…}``
cuyas comillas pueden venir escapadas (``\\"nemo\\"``) o no, según el chunk.

La extracción es por expresión regular anclada en ``nemo``/``fecha``/``cierre``
dentro del **mismo** objeto (``[^{}]*?`` impide cruzar de un objeto a otro);
nunca se usa ``eval``/``exec``. Se recorren todos los puntos y se devuelve el de
fecha mayor, porque el orden del payload no está garantizado.

La fecha ``$D`` ya es el día bursátil en hora de Chile: se usa el ``YYYY-MM-DD``
literal, sin conversión desde UTC (§4.3).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from ..fetch import fetch_text
from ..quote import Quote, QuoteFormatError, close_desde_decimal
from . import SourceError

URL_BASE = "https://www.dividendera.cl/"
FUENTE = "dividendera"

# La página real pesa 500-650 KB; por debajo de este piso es una página de error
# o de bloqueo, no la ficha con la serie de cierres.
MIN_BYTES = 100_000

# Firmas de página de bloqueo (mismas que ``fetch``); se revisan también acá para
# que el adaptador falle con un motivo propio si se lo llama con el cuerpo ya leído.
_BLOQUEO_MARCAS = (
    "vercel security checkpoint",
    "just a moment",
    "cf-chl",
)

_NEMO_RE = re.compile(r"^[A-Z0-9]{1,15}$")
_NUMERO = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
# Comilla de cierre de un string del payload: cero o más backslashes y luego ``"``.
_COMILLA = r'\\*"'


def url_de(nemo: str) -> str:
    """URL de la ficha del nemo; se valida el nemo antes de armar la ruta."""

    if not isinstance(nemo, str) or not _NEMO_RE.fullmatch(nemo):
        raise SourceError(
            f"nemo inválido para dividendera: {nemo!r}; se exige el formato ^[A-Z0-9]{{1,15}}$"
        )
    return f"{URL_BASE}{nemo}"


def _patron(nemo: str) -> re.Pattern[str]:
    """Objeto de precio del nemo: ``nemo`` + ``fecha`` + ``cierre`` en el mismo bloque."""

    return re.compile(
        _COMILLA
        + "nemo"
        + _COMILLA
        + r"\s*:\s*"
        + _COMILLA
        + re.escape(nemo)
        + _COMILLA
        + r"[^{}]*?"
        + _COMILLA
        + "fecha"
        + _COMILLA
        + r"\s*:\s*"
        + _COMILLA
        + r"\$D(\d{4}-\d{2}-\d{2})T"
        + r"[^{}]*?"
        + _COMILLA
        + "cierre"
        + _COMILLA
        + r"\s*:\s*("
        + _NUMERO
        + ")",
        re.DOTALL,
    )


def _marca_de_bloqueo(html: str) -> str | None:
    minusculas = html.lower()
    for marca in _BLOQUEO_MARCAS:
        if marca in minusculas:
            return marca
    return None


def parse_quote(html: str, nemo: str) -> Quote:
    """Cotización del punto de fecha máxima del nemo, o ``SourceError``."""

    if not isinstance(html, str) or not html:
        raise SourceError(f"la respuesta de dividendera para {nemo} está vacía")

    marca = _marca_de_bloqueo(html)
    if marca is not None:
        raise SourceError(
            f"la respuesta de dividendera para {nemo} es una página de bloqueo ({marca}); "
            "no se intenta evadir el mecanismo del sitio"
        )

    tamano = len(html.encode("utf-8"))
    if tamano < MIN_BYTES:
        raise SourceError(
            f"la respuesta de dividendera para {nemo} es demasiado pequeña "
            f"({tamano} bytes < {MIN_BYTES}); se espera la ficha completa con la serie "
            "de cierres, no una página de error"
        )

    mejor_fecha: date | None = None
    mejor_valor: Decimal | None = None
    for coincidencia in _patron(nemo).finditer(html):
        try:
            fecha = date.fromisoformat(coincidencia.group(1))
        except ValueError:
            continue
        try:
            valor = Decimal(coincidencia.group(2))
        except InvalidOperation:
            continue
        if not valor.is_finite() or valor <= 0:
            continue
        if mejor_fecha is None or fecha > mejor_fecha:
            mejor_fecha = fecha
            mejor_valor = valor

    if mejor_fecha is None or mejor_valor is None:
        raise SourceError(
            f"dividendera no trae cierres para {nemo} (posible cambio de nemo o de layout)"
        )

    try:
        cierre = close_desde_decimal(mejor_valor)
    except QuoteFormatError as exc:
        raise SourceError(
            f"el cierre de dividendera para {nemo} no es válido: {exc}"
        ) from None
    return Quote(date=mejor_fecha, close=cierre)


def cargar(nemo: str, con_indice: bool = False) -> tuple[Quote, None]:
    """Una sola petición a la ficha del nemo. Esta fuente no expone serie de índice."""

    quote = parse_quote(fetch_text(url_de(nemo), min_bytes=MIN_BYTES), nemo)
    return quote, None
