"""Backfill derivado: puntos semimensuales a partir de la serie de índice.

El índice de LedgiFi no es una cuota publicada: se usa solo como razón para
reconstruir hacia atrás el valor de la cuota en las fechas del índice. El
resultado vive en su propio archivo (``<TICKER>.backfill.json``) y nunca se
mezcla con el feed oficial. Este módulo no toca red ni disco.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .catalog import Fund
from .quote import Quote
from .sources.ledgifi import IndexPoint
from .store import CURRENCY, Feed

BACKFILL_MIN = 1
BACKFILL_MAX = 155
_CUATRO_DECIMALES = Decimal("0.0001")


class BackfillError(Exception):
    """Parámetros o datos que impiden generar el backfill derivado."""


def construir_backfill(
    feed_actual: Feed | None,
    serie_indice: Sequence[IndexPoint],
    n: int,
    fund: Fund,
) -> Feed:
    """Deriva ``n`` puntos anteriores al último punto oficial del fondo.

    Levanta ``BackfillError`` si no hay referencia, si el índice no cubre la
    fecha del último punto o si ``n`` no está en ``[BACKFILL_MIN, BACKFILL_MAX]``.
    """

    if not BACKFILL_MIN <= n <= BACKFILL_MAX:
        raise BackfillError(
            f"--backfill {n} está fuera de rango ({BACKFILL_MIN}-{BACKFILL_MAX})"
        )
    if feed_actual is None or feed_actual.last is None:
        raise BackfillError(
            f"{fund.ticker} no tiene punto oficial: no hay referencia para derivar el backfill"
        )

    ultimo = feed_actual.last
    # Un dict por fecha también deduplica: si el índice repite una fecha, prevalece
    # la última lectura y el feed derivado nunca queda con fechas duplicadas.
    por_fecha: dict[date, Decimal] = {punto.date: punto.value for punto in serie_indice}
    if ultimo.date not in por_fecha:
        raise BackfillError(
            f"la serie de índice no trae el punto {ultimo.date.isoformat()} "
            f"({fund.ticker}); no se puede derivar el backfill"
        )
    indice_ultimo = por_fecha[ultimo.date]
    if not indice_ultimo.is_finite() or indice_ultimo <= 0:
        raise BackfillError(
            f"el índice del {ultimo.date.isoformat()} no es un valor positivo "
            f"({indice_ultimo}); no se puede derivar el backfill"
        )

    anteriores = sorted(fecha for fecha in por_fecha if fecha < ultimo.date)
    if len(anteriores) < n:
        raise BackfillError(
            f"--backfill {n} excede los {len(anteriores)} puntos de índice anteriores "
            f"a {ultimo.date.isoformat()}; no se recorta la serie"
        )

    puntos: list[Quote] = []
    for fecha in anteriores[-n:]:
        valor = (
            Decimal(str(ultimo.close)) * por_fecha[fecha] / indice_ultimo
        ).quantize(_CUATRO_DECIMALES, rounding=ROUND_HALF_UP)
        puntos.append(Quote(date=fecha, close=float(valor)))

    return Feed(
        ticker=fund.ticker,
        name=fund.name,
        currency=CURRENCY,
        source=f"{fund.source}#indice",
        updated=puntos[-1].date,
        data=puntos,
    )
