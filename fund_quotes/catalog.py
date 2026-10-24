"""Registro estático de los fondos soportados (allowlist de tickers).

Cada fondo declara su **cadena de fuentes** en orden de precedencia: la primera es
la primaria y las siguientes son respaldos que el CLI intenta si la anterior
lanza ``FetchError``/``SourceError`` (§4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TICKER_RE = re.compile(r"^[A-Z0-9]{1,15}$")


class CatalogError(ValueError):
    """Ticker desconocido o inválido."""


@dataclass(frozen=True)
class Fund:
    """Un fondo del catálogo, con su cadena de fuentes verificadas."""

    ticker: str
    name: str
    run: str
    sources: tuple[str, ...]
    url: str
    supports_backfill: bool = False

    @property
    def source(self) -> str:
        """Fuente primaria (la primera de la cadena)."""

        return self.sources[0]

    @property
    def adapter(self) -> str:
        """Nombre del adaptador de la fuente primaria."""

        return self.source.partition(":")[0]


FUNDS: tuple[Fund, ...] = (
    Fund(
        ticker="CFMITNIPSA",
        name="FM IT NOW S&P IPSA",
        run="9019-0",
        # LedgiFi publica el valor cuota oficial (NAV); dividendera publica el
        # cierre bursátil y difiere ~0,15%, por eso va solo como respaldo.
        sources=("ledgifi:9019", "dividendera:CFMITNIPSA"),
        url="https://ledgifi.com/chile/fondos/fondo/9019",
        supports_backfill=True,
    ),
    Fund(
        ticker="CFINRENTAS",
        name="FI Independencia Rentas Inmobiliarias",
        run="7014-9",
        # La serie BOLSA de aindependencia está congelada desde 2026-10-19; se
        # mantiene como respaldo porque es la misma serie que publica dividendera.
        sources=("dividendera:CFINRENTAS", "aindependencia:bolsa"),
        url="https://www.dividendera.cl/CFINRENTAS",
        supports_backfill=False,
    ),
)

_BY_TICKER = {fund.ticker: fund for fund in FUNDS}


def get_fund(ticker: str) -> Fund:
    """Devuelve el fondo del catálogo o lanza ``CatalogError``."""

    if not isinstance(ticker, str) or not _TICKER_RE.fullmatch(ticker):
        raise CatalogError(
            f"ticker inválido: {ticker!r}; se exige el formato ^[A-Z0-9]{{1,15}}$"
        )
    try:
        return _BY_TICKER[ticker]
    except KeyError:
        disponibles = ", ".join(fund.ticker for fund in FUNDS)
        raise CatalogError(
            f"ticker desconocido: {ticker}; disponibles: {disponibles}"
        ) from None


def tickers() -> tuple[str, ...]:
    return tuple(fund.ticker for fund in FUNDS)
