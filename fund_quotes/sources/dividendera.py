"""Fuente C — Dividendera (primaria de CFINRENTAS y de CFMITNIPSA).

``https://www.dividendera.cl/<NEMO>`` es una app Next.js que responde HTTP 200
directo (sin proxy ni captcha) y embebe los cierres diarios de la Bolsa de
Santiago en los chunks ``self.__next_f.push([1,"..."])``. Cada punto es un objeto
``{"id":…,"nemo":…,"fecha":"$D<YYYY-MM-DD>T00:00:00.000Z","cierre":…,"volumen":…}``
cuyas comillas pueden venir escapadas (``\"nemo\"``) o no, según el chunk.

La extracción es por expresión regular anclada en ``nemo``/``fecha``/``cierre``
dentro del **mismo** objeto (``[^{}]*?`` impide cruzar de un objeto a otro);
nunca se usa ``eval``/``exec``. Se recorren **todos** los puntos, se deduplica
por fecha y se devuelven ordenados de forma ascendente: el adaptador entrega la
serie completa (2400+ puntos desde 2017) y el recorte lo decide el store/CLI
(catch-up y siembra de historia).

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


def parse_series(html: str, nemo: str) -> list[Quote]:
    """Serie completa del nemo, ascendente por fecha y sin duplicados."""

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

    # Un dict por fecha: si el payload repite una fecha, prevalece la última
    # lectura y la serie nunca queda con duplicados.
    por_fecha: dict[date, Decimal] = {}
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
        por_fecha[fecha] = valor

    if not por_fecha:
        raise SourceError(
            f"dividendera no trae cierres para {nemo} (posible cambio de nemo o de layout)"
        )

    serie: list[Quote] = []
    for fecha in sorted(por_fecha):
        try:
            cierre = close_desde_decimal(por_fecha[fecha])
        except QuoteFormatError as exc:
            raise SourceError(
                f"el cierre de dividendera para {nemo} del {fecha.isoformat()} no es válido: {exc}"
            ) from None
        serie.append(Quote(date=fecha, close=cierre))
    return serie


def parse_quote(html: str, nemo: str) -> Quote:
    """Cotización del punto de fecha máxima del nemo, o ``SourceError``.

    Se conserva para las verificaciones puntuales; el contrato del adaptador es
    :func:`parse_series`.
    """

    return parse_series(html, nemo)[-1]


def cargar(nemo: str, con_indice: bool = False) -> tuple[list[Quote], None]:
    """Una sola petición a la ficha del nemo; devuelve la serie completa.

    El adaptador no recorta: el catch-up y la siembra los decide el store.
    Esta fuente no expone serie de índice.
    """

    serie = parse_series(fetch_text(url_de(nemo), min_bytes=MIN_BYTES), nemo)
    return serie, None
