"""Contrato de archivo, merge append-only y escritura atómica.

El JSON publicado es determinista byte a byte: claves en orden fijo, ``indent=2``,
UTF-8 sin BOM y un salto de línea final (REQ-STO-004).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .catalog import Fund
from .quote import MAX_CLOSE, Quote

KEYS = ("ticker", "name", "currency", "source", "updated", "data")
CURRENCY = "CLP"
_TOLERANCIA = 1e-6


class FeedError(Exception):
    """El feed existe pero no se puede leer o no cumple el contrato."""


@dataclass
class Feed:
    """Contenido completo de un archivo de cotizaciones."""

    ticker: str
    name: str
    currency: str
    source: str
    updated: date
    data: list[Quote]

    @property
    def last(self) -> Quote | None:
        return self.data[-1] if self.data else None


def _ordenado(feed: Feed) -> dict:
    return {
        "ticker": feed.ticker,
        "name": feed.name,
        "currency": feed.currency,
        "source": feed.source,
        "updated": feed.updated.isoformat(),
        "data": [punto.to_dict() for punto in feed.data],
    }


def serialize(feed: Feed) -> bytes:
    """Serializa el feed de forma determinista (mismas entradas -> mismos bytes)."""

    texto = json.dumps(_ordenado(feed), ensure_ascii=False, indent=2)
    return (texto + "\n").encode("utf-8")


def feed_path(directorio: str | Path, ticker: str) -> Path:
    return Path(directorio) / f"{ticker}.json"


def backfill_path(directorio: str | Path, ticker: str) -> Path:
    return Path(directorio) / f"{ticker}.backfill.json"


def _validar_contrato(datos: object, fund: Fund, origen: Path) -> Feed:
    def falla(motivo: str) -> FeedError:
        return FeedError(f"el feed existente no se pudo leer ({origen}): {motivo}")

    if not isinstance(datos, dict):
        raise falla("la raíz no es un objeto JSON")
    if set(datos) != set(KEYS):
        raise falla(f"claves inesperadas: {sorted(datos)}; se esperan {list(KEYS)}")

    ticker = datos["ticker"]
    name = datos["name"]
    currency = datos["currency"]
    source = datos["source"]
    updated = datos["updated"]
    filas = datos["data"]

    if ticker != fund.ticker:
        raise falla(f"el ticker del archivo es {ticker!r} y se esperaba {fund.ticker!r}")
    if not isinstance(name, str) or not name:
        raise falla("el campo name no es un texto válido")
    if currency != CURRENCY:
        raise falla(f"currency debe ser {CURRENCY}")
    if not isinstance(source, str) or not source:
        raise falla("el campo source no es un texto válido")
    if not isinstance(updated, str):
        raise falla("el campo updated no es un texto ISO")
    if not isinstance(filas, list) or not filas:
        raise falla("data debe ser una lista con al menos un punto")

    puntos: list[Quote] = []
    anterior: date | None = None
    for posicion, fila in enumerate(filas):
        if not isinstance(fila, dict) or set(fila) != {"date", "close"}:
            raise falla(f"el punto {posicion} no tiene exactamente date y close")
        fecha_txt = fila["date"]
        cierre = fila["close"]
        if not isinstance(fecha_txt, str):
            raise falla(f"el punto {posicion} no tiene date ISO")
        try:
            fecha = date.fromisoformat(fecha_txt)
        except ValueError:
            raise falla(f"el punto {posicion} tiene una fecha inválida: {fecha_txt!r}") from None
        if isinstance(cierre, bool) or not isinstance(cierre, (int, float)):
            raise falla(f"el punto {posicion} tiene un close no numérico")
        if not (0 < float(cierre) < float(MAX_CLOSE)):
            raise falla(f"el punto {posicion} tiene un close fuera de rango: {cierre!r}")
        if anterior is not None and fecha <= anterior:
            raise falla("las fechas no están ordenadas de forma ascendente y sin duplicados")
        anterior = fecha
        puntos.append(Quote(date=fecha, close=float(cierre)))

    try:
        fecha_updated = date.fromisoformat(updated)
    except ValueError:
        raise falla(f"el campo updated no es una fecha ISO: {updated!r}") from None
    if fecha_updated != puntos[-1].date:
        raise falla("el campo updated no coincide con la fecha del último punto")

    return Feed(
        ticker=ticker,
        name=name,
        currency=currency,
        source=source,
        updated=fecha_updated,
        data=puntos,
    )


def read_feed(ruta: str | Path, fund: Fund) -> Feed | None:
    """Lee y valida un feed. ``None`` si no existe; ``FeedError`` si está corrupto."""

    ruta = Path(ruta)
    if not ruta.exists():
        return None
    if not ruta.is_file():
        raise FeedError(f"el feed existente no se pudo leer ({ruta}): no es un archivo")
    try:
        crudo = ruta.read_bytes()
    except OSError as exc:
        raise FeedError(f"el feed existente no se pudo leer ({ruta}): {exc}") from None
    try:
        texto = crudo.decode("utf-8")
    except UnicodeDecodeError:
        raise FeedError(
            f"el feed existente no se pudo leer ({ruta}): no es UTF-8 válido"
        ) from None
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise FeedError(
            f"el feed existente no se pudo leer ({ruta}): JSON inválido ({exc.msg})"
        ) from None
    except ValueError:
        raise FeedError(
            f"el feed existente no se pudo leer ({ruta}): contenido inválido"
        ) from None
    return _validar_contrato(datos, fund, ruta)


def nuevo_feed(fund: Fund, quote: Quote, source: str | None = None) -> Feed:
    return Feed(
        ticker=fund.ticker,
        name=fund.name,
        currency=CURRENCY,
        source=source or fund.source,
        updated=quote.date,
        data=[quote],
    )


def merge(
    existente: Feed | None,
    quote: Quote,
    fund: Fund,
    source: str | None = None,
) -> tuple[Feed, str]:
    """Fusiona un punto con el feed previo, sin reescribir historia.

    Estados: ``nuevo``, ``agregado``, ``sin_cambios``, ``conflicto`` (mismo día
    con otro valor) y ``antiguo`` (fecha anterior al último punto).

    ``source`` es la fuente que entregó el punto: queda registrada como ``source``
    del feed (contrato §5.1) porque con la cadena primaria/respaldo la fuente
    efectiva puede no ser la primaria del catálogo.
    """

    if existente is None:
        return nuevo_feed(fund, quote, source), "nuevo"

    por_fecha = {punto.date: punto for punto in existente.data}
    if quote.date in por_fecha:
        previo = por_fecha[quote.date]
        if abs(previo.close - quote.close) <= _TOLERANCIA:
            return existente, "sin_cambios"
        return existente, "conflicto"

    ultimo = existente.data[-1]
    if quote.date < ultimo.date:
        return existente, "antiguo"

    datos = list(existente.data)
    datos.append(quote)
    fusionado = Feed(
        ticker=existente.ticker,
        name=existente.name,
        currency=existente.currency,
        source=source or existente.source,
        updated=quote.date,
        data=datos,
    )
    return fusionado, "agregado"


def write_atomic(ruta: str | Path, contenido: bytes) -> None:
    """Escribe con archivo temporal en el mismo directorio + ``os.replace``."""

    ruta = Path(ruta)
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FeedError(f"no se pudo crear el directorio {ruta.parent}: {exc}") from None

    temporal: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=str(ruta.parent), prefix=".tmp-", suffix=".json", delete=False
        ) as manejador:
            temporal = manejador.name
            manejador.write(contenido)
            manejador.flush()
            os.fsync(manejador.fileno())
        os.replace(temporal, ruta)
        temporal = None
    except OSError as exc:
        raise FeedError(f"no se pudo escribir {ruta}: {exc}") from None
    finally:
        if temporal is not None:
            try:
                os.unlink(temporal)
            except OSError:
                pass


def write_feed(ruta: str | Path, feed: Feed) -> None:
    write_atomic(ruta, serialize(feed))
