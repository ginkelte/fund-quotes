"""Registro estático de los fondos soportados (allowlist de tickers)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TICKER_RE = re.compile(r"^[A-Z0-9]{1,15}$")


class CatalogError(ValueError):
    """Ticker desconocido o inválido."""


@dataclass(frozen=True)
class Fund:
    """Un fondo del catálogo, con su fuente verificada."""

    ticker: str
    name: str
    run: str
    source: str
    url: str
    adapter: str
    supports_backfill: bool = False


FUNDS: tuple[Fund, ...] = (
    Fund(
        ticker="CFMITNIPSA",
        name="FM IT NOW S&P IPSA",
        run="9019-0",
        source="ledgifi:9019",
        url="https://ledgifi.com/chile/fondos/fondo/9019",
        adapter="ledgifi",
        supports_backfill=True,
    ),
    Fund(
        ticker="CFINRENTAS",
        name="FI Independencia Rentas Inmobiliarias",
        run="7014-9",
        source="aindependencia:bolsa",
        url="https://www.aindependencia.cl/fondos/",
        adapter="aindependencia",
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
