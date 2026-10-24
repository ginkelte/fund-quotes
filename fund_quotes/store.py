"""Contrato de archivo, merge append-only (multi-punto) y escritura atómica.

El JSON publicado es determinista byte a byte: claves en orden fijo, ``indent=2``,
UTF-8 sin BOM y un salto de línea final (REQ-STO-004).
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
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


def _normalizar_serie(nuevos: Iterable[Quote]) -> list[Quote]:
    """Serie ascendente y sin duplicados: si una fecha se repite, gana la última."""

    por_fecha: dict[date, Quote] = {}
    for punto in nuevos:
        por_fecha[punto.date] = punto
    return [por_fecha[fecha] for fecha in sorted(por_fecha)]


def nuevo_feed(
    fund: Fund, quotes: Quote | Iterable[Quote], source: str | None = None
) -> Feed:
    """Feed inicial con los puntos indicados (admite un punto o una serie)."""

    serie = _normalizar_serie([quotes] if isinstance(quotes, Quote) else quotes)
    if not serie:
        raise FeedError(f"{fund.ticker}: no se puede crear un feed sin puntos")
    return Feed(
        ticker=fund.ticker,
        name=fund.name,
        currency=CURRENCY,
        source=source or fund.source,
        updated=serie[-1].date,
        data=serie,
    )


@dataclass
class MergeResult:
    """Resultado de fusionar una serie con el feed previo.

    ``agregados`` son los puntos efectivamente incorporados (ascendente) y
    ``descartados`` los que no entraron por duplicado, conflicto de valor o
    fecha anterior al último punto publicado.
    """

    feed: Feed
    estado: str
    agregados: list[Quote]
    descartados: list[Quote]


def clasificar(existente: Feed | None, nuevos: Iterable[Quote]) -> str:
    """Estado de un lote que no agrega puntos: ``conflicto``, ``antiguo`` o ``sin_cambios``."""

    serie = _normalizar_serie(nuevos)
    if existente is None or not serie:
        return "sin_cambios"
    por_fecha = {punto.date: punto for punto in existente.data}
    for punto in serie:
        previo = por_fecha.get(punto.date)
        if previo is not None and abs(previo.close - punto.close) > _TOLERANCIA:
            return "conflicto"
    ultimo = existente.data[-1]
    if all(punto.date < ultimo.date for punto in serie):
        return "antiguo"
    return "sin_cambios"


def merge(
    existente: Feed | None,
    nuevos: Quote | Iterable[Quote],
    fund: Fund,
    source: str | None = None,
) -> MergeResult:
    """Fusiona uno o varios puntos con el feed previo, sin reescribir historia.

    Se agregan **todos** los puntos con fecha posterior al último punto publicado;
    los duplicados y los anteriores se descartan (``descartados``). El resultado
    queda ascendente, sin fechas duplicadas y append-only.

    Estados: ``nuevo`` (no había feed), ``agregado`` (entró al menos un punto),
    ``sin_cambios`` (todo ya estaba), ``conflicto`` (mismo día con otro valor) y
    ``antiguo`` (todas las fechas son anteriores al último punto).

    ``source`` es la fuente que entregó los puntos: queda registrada como
    ``source`` del feed (contrato §5.1) porque con la cadena primaria/respaldo la
    fuente efectiva puede no ser la primaria del catálogo.
    """

    serie = _normalizar_serie([nuevos] if isinstance(nuevos, Quote) else nuevos)

    if existente is None:
        feed = nuevo_feed(fund, serie, source)
        return MergeResult(feed=feed, estado="nuevo", agregados=list(feed.data), descartados=[])

    if not serie:
        return MergeResult(feed=existente, estado="sin_cambios", agregados=[], descartados=[])

    ultimo = existente.data[-1]
    por_fecha = {punto.date: punto for punto in existente.data}
    agregados: list[Quote] = []
    descartados: list[Quote] = []
    for punto in serie:
        if punto.date in por_fecha or punto.date < ultimo.date:
            descartados.append(punto)
            continue
        agregados.append(punto)
        por_fecha[punto.date] = punto

    if not agregados:
        return MergeResult(
            feed=existente,
            estado=clasificar(existente, serie),
            agregados=[],
            descartados=descartados,
        )

    datos = list(existente.data) + agregados
    fusionado = Feed(
        ticker=existente.ticker,
        name=existente.name,
        currency=existente.currency,
        source=source or existente.source,
        updated=datos[-1].date,
        data=datos,
    )
    return MergeResult(
        feed=fusionado, estado="agregado", agregados=agregados, descartados=descartados
    )


def serie_habil(serie: Iterable[Quote]) -> list[Quote]:
    """Puntos en día hábil (L-V), ascendentes y sin duplicados."""

    return [punto for punto in _normalizar_serie(serie) if punto.date.weekday() < 5]


def sembrar(
    fund: Fund,
    serie: Iterable[Quote],
    dias: int,
    source: str | None = None,
) -> Feed:
    """Feed inicial con los últimos ``dias`` días hábiles de la serie de la fuente.

    La siembra es la única vía por la que se escribe historia anterior a la
    primera corrida: no reescribe un feed existente (el CLI no la llama en ese
    caso) y no pasa por la guarda de anomalía, porque son cierres oficiales ya
    publicados por la fuente. Si la fuente trae menos días hábiles que ``dias``,
    se siembra todo lo disponible.
    """

    if dias < 1:
        raise FeedError(f"--sembrar-historia debe ser un entero positivo (recibido {dias})")
    habiles = serie_habil(serie)
    if not habiles:
        raise FeedError(
            f"{fund.ticker}: la fuente no trae días hábiles para sembrar la historia"
        )
    return nuevo_feed(fund, habiles[-dias:], source)


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
