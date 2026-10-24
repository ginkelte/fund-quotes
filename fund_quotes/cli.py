"""CLI del feed: parsea flags, orquesta por fondo y decide el código de salida.

No parsea HTML ni escribe archivos: delega en los adaptadores y en ``store``.
El pipeline trabaja por **series**, no por puntos sueltos: cada adaptador puede
traer varios cierres y el CLI hace el catch-up (agrega todos los posteriores al
último punto publicado) o la siembra inicial de historia con ``--sembrar-historia``.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo

from . import catalog, guards, status_page, store
from .backfill import BACKFILL_MAX, BACKFILL_MIN, BackfillError, construir_backfill
from .catalog import Fund
from .fetch import FetchError
from .quote import Quote
from .sources import SourceError, aindependencia, dividendera, ledgifi
from .sources.ledgifi import IndexPoint

ZONA = ZoneInfo("America/Santiago")

# Cada entrada recibe la referencia del catálogo (``<adaptador>:<argumento>``) y si
# hace falta la serie de índice. Todos los adaptadores devuelven ``list[Quote]``
# ascendente; los de una sola URL ignoran el argumento y dividendera lo usa como nemo.
ADAPTADORES = {
    "ledgifi": lambda _ref, con_indice: ledgifi.cargar(con_indice=con_indice),
    "aindependencia": lambda _ref, con_indice: aindependencia.cargar(con_indice=con_indice),
    "dividendera": lambda ref, con_indice: dividendera.cargar(ref, con_indice=con_indice),
}

# Raíz bajo la cual deben quedar todas las rutas de escritura (§9). Se detecta
# desde el paquete (``<repo>/fund_quotes/cli.py``) y los tests la reemplazan.
RAIZ_REPO = Path(__file__).resolve().parent.parent

SALIDA_OK = 0
SALIDA_CONFIG = 1
SALIDA_PARCIAL = 2
SALIDA_GUARDA = 3

# Ventana de siembra de historia inicial (días hábiles hacia atrás).
SIEMBRA_MIN = 1
SIEMBRA_MAX = 800


class Estado(StrEnum):
    """Estado de un fondo en la corrida; sus valores son los del contrato de salida."""

    OK = "ok"
    SIN_CAMBIOS = "sin_cambios"
    CONFLICTO = "conflicto"
    ANTIGUO = "antiguo"
    ANOMALIA = "anomalia"
    FALLA = "falla"


@dataclass
class Resultado:
    """Resultado de un fondo. ``feed`` es lo que se escribe; ``None`` = no tocar."""

    fund: Fund
    estado: Estado
    feed: store.Feed | None = None
    quote: Quote | None = None
    lineas: list[str] = field(default_factory=list)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fund_quotes",
        description=(
            "Publica el feed de cotizaciones diarias de dos fondos chilenos en el "
            "formato del proveedor JSON de Portfolio Performance."
        ),
    )
    parser.add_argument(
        "--out",
        default="docs/quotes",
        metavar="DIR",
        help="directorio de los JSON publicados (por defecto docs/quotes)",
    )
    parser.add_argument(
        "--status-page",
        default="docs/index.html",
        metavar="ARCHIVO",
        help="ruta de la página de estado (por defecto docs/index.html)",
    )
    parser.add_argument(
        "--fondo",
        action="append",
        nargs="+",
        metavar="TICKER",
        help="limita la corrida a uno o más tickers del catálogo",
    )
    parser.add_argument(
        "--force-anomaly",
        action="store_true",
        help="acepta un salto mayor a 5,00%% dejando registro del forzado",
    )
    parser.add_argument(
        "--backfill",
        type=int,
        metavar="N",
        help=f"genera N puntos de índice derivados ({BACKFILL_MIN}-{BACKFILL_MAX}) en un archivo aparte",
    )
    parser.add_argument(
        "--sembrar-historia",
        type=int,
        metavar="N",
        default=None,
        help=(
            "si el feed no existe, lo crea con los últimos N días hábiles de la "
            f"serie de la fuente ({SIEMBRA_MIN}-{SIEMBRA_MAX}); con feed existente es no-op"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="calcula y reporta sin escribir archivos",
    )
    parser.add_argument(
        "--today",
        metavar="YYYY-MM-DD",
        help="fecha de referencia (por defecto hoy en America/Santiago)",
    )
    return parser


def _hoy(texto: str | None) -> date:
    if texto is None:
        return datetime.now(ZONA).date()
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise ValueError(
            f"--today inválido: {texto!r}; se espera una fecha YYYY-MM-DD"
        ) from None


def _ruta_segura(texto: str, etiqueta: str) -> Path:
    """Resuelve la ruta y exige que quede dentro de la raíz del repo (REQ-SEC-001/§9)."""

    ruta = Path(texto)
    if ".." in ruta.parts:
        raise ValueError(f"{etiqueta} no puede contener '..': {texto}")
    raiz = RAIZ_REPO.resolve()
    destino = ruta.resolve()
    if destino != raiz and not destino.is_relative_to(raiz):
        raise ValueError(f"{etiqueta} queda fuera de la raíz del repo ({raiz}): {texto}")
    return destino


def _seleccion(valores: list[list[str]] | None) -> list[Fund]:
    if not valores:
        return list(catalog.FUNDS)
    pedidos = [ticker for grupo in valores for ticker in grupo]
    vistos: list[Fund] = []
    for ticker in pedidos:
        fund = catalog.get_fund(ticker)
        if all(f.ticker != fund.ticker for f in vistos):
            vistos.append(fund)
    return vistos


def _close_txt(valor: float | Decimal) -> str:
    return f"{float(valor):.4f}".rstrip("0").rstrip(".")


def _linea_ok(fund: Fund, quote: Quote, fuente: str, nuevos: int) -> str:
    return (
        f"[OK] {fund.ticker} fecha={quote.date.isoformat()} "
        f"close={_close_txt(quote.close)} fuente={fuente} nuevos={nuevos}"
    )


def _linea_sin_cambios(fund: Fund, quote: Quote, fuente: str, motivo: str) -> str:
    return (
        f"[SIN CAMBIOS] {fund.ticker} fecha={quote.date.isoformat()} "
        f"close={_close_txt(quote.close)} fuente={fuente} motivo={motivo}"
    )


def _linea_anomalia(fund: Fund, exc: guards.AnomaliaDetectada) -> str:
    return (
        f"[ANOMALIA] {fund.ticker} "
        f"variacion={guards.formato_pct(exc.variacion, signo=True)} "
        f"umbral={guards.formato_pct(exc.umbral)} fecha={exc.fecha.isoformat()}"
    )


class _FalloFuentes(Exception):
    """Todas las fuentes de la cadena del fondo fallaron."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


def _cargar_fuente(
    referencia: str, con_indice: bool
) -> tuple[list[Quote], list[IndexPoint] | None]:
    """Ejecuta el adaptador de una referencia ``<adaptador>:<argumento>``."""

    adaptador, _, argumento = referencia.partition(":")
    cargador = ADAPTADORES.get(adaptador)
    if cargador is None:
        raise SourceError(f"fuente desconocida en el catálogo: {referencia!r}")
    return cargador(argumento, con_indice)


def _adquirir(
    fund: Fund, con_indice: bool
) -> tuple[list[Quote], list[IndexPoint] | None, str, list[str]]:
    """Recorre la cadena de fuentes del fondo: primaria y, si falla, respaldos.

    Devuelve ``(serie, indice, fuente_usada, avisos)``. Si la fuente que responde
    no es la primaria, se agrega un ``[AVISO]`` con el motivo del fallo primario.
    Si falla toda la cadena, lanza ``_FalloFuentes`` nombrando cada intento.

    El índice del backfill solo lo publica LedgiFi: si la primaria no lo trae y se
    pidió ``--backfill``, se busca en el resto de la cadena sin cambiar la fuente
    de la cuota. Si ningún eslabón lo trae, queda en ``None`` y el CLI degrada el
    backfill a un aviso (REQ-ADP-004).
    """

    motivos: list[str] = []
    serie: list[Quote] | None = None
    indice: list[IndexPoint] | None = None
    fuente = fund.source
    avisos: list[str] = []

    for posicion, referencia in enumerate(fund.sources):
        try:
            serie_cargada, indice_cargado = _cargar_fuente(referencia, con_indice)
        except (FetchError, SourceError) as exc:
            motivo = exc.motivo if isinstance(exc, FetchError) else str(exc)
            etiqueta = "primaria" if posicion == 0 else "respaldo"
            motivos.append(f"{etiqueta} {referencia}: {motivo}")
            continue
        serie = serie_cargada
        indice = indice_cargado
        fuente = referencia
        if posicion > 0:
            avisos.append(
                f"[AVISO] {fund.ticker} se usó la fuente de respaldo {referencia}: "
                f"la primaria {fund.source} falló ({motivos[0]})"
            )
        break

    if serie is None:
        if len(motivos) == 1:
            raise _FalloFuentes(motivos[0])
        raise _FalloFuentes("; ".join(motivos))

    if con_indice and indice is None:
        for referencia in fund.sources:
            if referencia == fuente:
                continue
            try:
                _, indice_otro = _cargar_fuente(referencia, True)
            except (FetchError, SourceError):
                continue
            if indice_otro:
                indice = indice_otro
                break

    return serie, indice, fuente, avisos


def _separar_por_fecha(
    fund: Fund, serie: list[Quote], hoy: date, lineas: list[str]
) -> list[Quote]:
    """Descarta fechas implausibles (posteriores a hoy + 1) sin abortar el resto."""

    validos: list[Quote] = []
    for punto in serie:
        try:
            guards.validar_fecha(punto, hoy)
        except guards.FechaImplausible:
            limite = (hoy + timedelta(days=1)).isoformat()
            lineas.append(
                f"[ANOMALIA] {fund.ticker} fecha={punto.date.isoformat()} "
                f"close={_close_txt(punto.close)} motivo=fecha implausible "
                f"(posterior a {limite})"
            )
            continue
        validos.append(punto)
    return validos


def _sembrar(
    fund: Fund,
    serie: list[Quote],
    fuente: str,
    args: argparse.Namespace,
    lineas: list[str],
) -> Resultado:
    """Crea el feed inicial con los últimos N días hábiles de la serie de la fuente.

    Los puntos sembrados no pasan por la guarda de anomalía: son cierres oficiales
    ya publicados por la fuente. Sí pasaron por la normalización numérica del
    adaptador y por el chequeo de fecha futura.
    """

    pedidos = args.sembrar_historia
    resultado = Resultado(fund=fund, estado=Estado.SIN_CAMBIOS, feed=None, lineas=lineas)
    try:
        feed = store.sembrar(fund, serie, pedidos, source=fuente)
    except store.FeedError as exc:
        resultado.estado = Estado.FALLA
        resultado.lineas.append(f"[FALLA] {fund.ticker} siembra: {exc}")
        return resultado

    resultado.estado = Estado.OK
    resultado.feed = feed
    resultado.quote = feed.data[-1]
    resultado.lineas.append(_linea_ok(fund, feed.data[-1], fuente, len(feed.data)))
    resultado.lineas.append(
        f"[AVISO] {fund.ticker} siembra de historia: {len(feed.data)} días hábiles "
        f"desde {feed.data[0].date.isoformat()} hasta {feed.updated.isoformat()} "
        "(cierres oficiales de la fuente; la guarda de anomalía no aplica)"
    )
    if len(feed.data) < pedidos:
        resultado.lineas.append(
            f"[AVISO] {fund.ticker} la fuente solo trajo {len(feed.data)} días hábiles; "
            f"se sembró todo lo disponible (se pidieron {pedidos})"
        )
    return resultado


def _procesar_fondo(
    fund: Fund,
    existente: store.Feed | None,
    hoy: date,
    args: argparse.Namespace,
) -> tuple[Resultado, store.Feed | None]:
    """Un fondo: fetch -> parse -> (siembra | guardas por punto) -> merge -> backfill."""

    necesita_indice = args.backfill is not None and fund.supports_backfill
    try:
        serie, indice, fuente, avisos = _adquirir(fund, necesita_indice)
    except _FalloFuentes as exc:
        return (
            Resultado(
                fund=fund,
                estado=Estado.FALLA,
                feed=None,
                lineas=[f"[FALLA] {fund.ticker} fuente={fund.source} motivo={exc.motivo}"],
            ),
            None,
        )

    lineas: list[str] = list(avisos)
    validos = _separar_por_fecha(fund, serie, hoy, lineas)
    if not validos:
        return Resultado(fund=fund, estado=Estado.ANOMALIA, feed=None, lineas=lineas), None

    if args.sembrar_historia is not None:
        if existente is None:
            resultado = _sembrar(fund, validos, fuente, args, lineas)
            return resultado, _backfill_de(resultado, existente, indice, args)
        lineas.append(
            f"[AVISO] {fund.ticker} --sembrar-historia no se aplica: el feed ya existe "
            f"con {len(existente.data)} puntos (la siembra solo crea feeds nuevos)"
        )

    base = existente.data if existente is not None else []
    fusion_completa = store.merge(existente, validos, fund, source=fuente)
    frontera = base[-1].date if base else None
    nuevos = fusion_completa.agregados
    # El tramo nuevo (posterior a la frontera) pasa por la guarda de anomalía.
    # Los huecos rellenados dentro del rango ya publicado son historia oficial
    # de la fuente y entran sin guarda, con aviso.
    tramo_nuevo = [punto for punto in nuevos if frontera is None or punto.date > frontera]
    relleno = [punto for punto in nuevos if frontera is not None and punto.date <= frontera]
    if relleno:
        lineas.append(
            f"[AVISO] {fund.ticker} se rellenaron {len(relleno)} día(s) faltantes dentro "
            f"del rango ya publicado (catch-up)"
        )

    previo = existente.last if existente is not None else None
    aceptados: list[Quote] = []
    anomalias: list[guards.AnomaliaDetectada] = []
    for punto in tramo_nuevo:
        try:
            guards.validar_anomalia(punto, previo)
        except guards.AnomaliaDetectada as exc:
            if not args.force_anomaly:
                anomalias.append(exc)
                continue
            lineas.append(
                f"[AVISO] {fund.ticker} anomalía forzada con --force-anomaly: "
                f"variacion={guards.formato_pct(exc.variacion, signo=True)} "
                f"umbral={guards.formato_pct(exc.umbral)} fecha={exc.fecha.isoformat()}"
            )
        aceptados.append(punto)
        previo = punto

    lote = sorted(relleno + aceptados, key=lambda punto: punto.date)
    fusion = (
        fusion_completa
        if len(lote) == len(nuevos)
        else store.merge(existente, lote, fund, source=fuente)
    )
    resultado = Resultado(fund=fund, estado=Estado.SIN_CAMBIOS, feed=None, lineas=lineas)
    estado_merge = fusion.estado

    if anomalias:
        resultado.estado = Estado.ANOMALIA
        resultado.quote = aceptados[-1] if aceptados else None
        if aceptados:
            # El tramo aceptado sí se publica: el rechazo es punto a punto (§8).
            resultado.feed = fusion.feed
            resultado.lineas.append(
                _linea_ok(fund, aceptados[-1], fuente, len(fusion.agregados))
            )
        for exc in anomalias:
            resultado.lineas.append(_linea_anomalia(fund, exc))
        return resultado, _backfill_de(resultado, existente, indice, args)

    ultimo = validos[-1]
    if estado_merge in ("agregado", "nuevo"):
        resultado.estado = Estado.OK
        resultado.feed = fusion.feed
        resultado.quote = fusion.feed.data[-1]
        resultado.lineas.append(
            _linea_ok(fund, fusion.feed.data[-1], fuente, len(fusion.agregados))
        )
    elif estado_merge == "conflicto":
        guardado = ultimo
        publicado = ultimo
        if existente is not None:
            conflicto = store.primer_conflicto(existente, aceptados)
            if conflicto is not None:
                guardado, publicado = conflicto
        resultado.estado = Estado.CONFLICTO
        resultado.quote = guardado
        resultado.lineas.append(
            _linea_sin_cambios(fund, guardado, fuente, "ya_existia_con_otro_valor")
        )
        resultado.lineas.append(
            f"[AVISO] {fund.ticker} el punto {guardado.date.isoformat()} ya existía con "
            f"otro valor: se conserva {_close_txt(guardado.close)} "
            f"(la fuente publicó {_close_txt(publicado.close)})"
        )
    elif estado_merge == "antiguo":
        resultado.estado = Estado.ANTIGUO
        resultado.quote = ultimo
        resultado.lineas.append(
            _linea_sin_cambios(fund, ultimo, fuente, "fecha_anterior_al_ultimo_punto")
        )
    else:
        resultado.estado = Estado.SIN_CAMBIOS
        resultado.quote = ultimo
        resultado.lineas.append(_linea_sin_cambios(fund, ultimo, fuente, "ya_publicado"))
        if fusion.descartados:
            ya_estaban = sum(1 for p in fusion.descartados if existente and any(
                q.date == p.date for q in existente.data))
            fuera = len(fusion.descartados) - ya_estaban
            if ya_estaban:
                lineas.append(
                    f"[AVISO] {fund.ticker} {ya_estaban} punto(s) de la fuente ya estaban "
                    f"publicados sin cambios; {fuera} quedaron fuera del rango del feed"
                )

    return resultado, _backfill_de(resultado, existente, indice, args)


def _backfill_de(
    resultado: Resultado,
    existente: store.Feed | None,
    indice: list[IndexPoint] | None,
    args: argparse.Namespace,
) -> store.Feed | None:
    """Backfill derivado del fondo, o ``None`` con el motivo como aviso (§5.2)."""

    if args.backfill is None:
        return None
    fund = resultado.fund
    if not fund.supports_backfill:
        resultado.lineas.append(f"[SIN CAMBIOS] {fund.ticker} backfill=no_disponible")
        return None

    base = resultado.feed if resultado.feed is not None else existente
    try:
        if indice is None:
            raise BackfillError(
                f"{fund.ticker} no expone serie de índice: el backfill no está disponible"
            )
        return construir_backfill(base, indice, args.backfill, fund)
    except BackfillError as exc:
        # El backfill es auxiliar: se degrada a aviso y no condiciona el feed
        # oficial ni el código de salida (§8).
        resultado.lineas.append(f"[AVISO] {fund.ticker} backfill: {exc}")
        return None


def _resumen_actions(lineas: list[str]) -> None:
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if not ruta:
        return
    try:
        with open(ruta, "a", encoding="utf-8") as manejador:
            manejador.write("## Feed de cotizaciones\n\n")
            manejador.writelines(f"- `{linea}`\n" for linea in lineas)
            manejador.write("\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        hoy = _hoy(args.today)
        seleccion = _seleccion(args.fondo)
        salida = _ruta_segura(args.out, "--out")
        pagina = _ruta_segura(args.status_page, "--status-page")
    except (ValueError, catalog.CatalogError) as exc:
        print(f"[FALLA] configuración: {exc}", file=sys.stderr)
        return SALIDA_CONFIG

    if args.backfill is not None and not (BACKFILL_MIN <= args.backfill <= BACKFILL_MAX):
        print(
            f"[FALLA] configuración: --backfill debe estar entre {BACKFILL_MIN} y "
            f"{BACKFILL_MAX} (recibido {args.backfill})",
            file=sys.stderr,
        )
        return SALIDA_CONFIG

    if args.sembrar_historia is not None and not (
        SIEMBRA_MIN <= args.sembrar_historia <= SIEMBRA_MAX
    ):
        print(
            f"[FALLA] configuración: --sembrar-historia debe estar entre {SIEMBRA_MIN} y "
            f"{SIEMBRA_MAX} (recibido {args.sembrar_historia})",
            file=sys.stderr,
        )
        return SALIDA_CONFIG

    # Fase 1: leer los feeds existentes antes de tocar nada (REQ-STO-003).
    feeds: dict[str, store.Feed | None] = {}
    for fund in seleccion:
        ruta = store.feed_path(salida, fund.ticker)
        try:
            feeds[fund.ticker] = store.read_feed(ruta, fund)
        except store.FeedError as exc:
            print(f"[FALLA] {fund.ticker} motivo={exc}", file=sys.stderr)
            return SALIDA_CONFIG

    # Fase 2: adquirir, parsear, aplicar guardas y fusionar. Un backfill fallido
    # ya no interrumpe la fase: se reporta como aviso dentro del fondo.
    resultados: list[Resultado] = []
    backfills: dict[str, store.Feed] = {}

    for fund in seleccion:
        resultado, backfill = _procesar_fondo(fund, feeds[fund.ticker], hoy, args)
        resultados.append(resultado)
        if backfill is not None:
            backfills[fund.ticker] = backfill

    lineas_stdout: list[str] = []
    for resultado in resultados:
        for linea in resultado.lineas:
            # El reporte por fondo va a stdout (REQ-CLI-002 / AC-05); los fallos se
            # duplican en stderr con su motivo accionable.
            print(linea)
            lineas_stdout.append(linea)
            if linea.startswith("[FALLA]"):
                print(linea, file=sys.stderr)

    # Fase 3: escribir solo lo que quedó al día (REQ-PUB-001). Con código 1 por
    # "todos los fondos fallaron" no se modifica ningún archivo (§8).
    todo_fallo = not resultados or all(r.estado is Estado.FALLA for r in resultados)
    error_escritura = False
    if not args.dry_run and not todo_fallo:
        for resultado in resultados:
            if resultado.feed is not None and resultado.estado in (Estado.OK, Estado.ANOMALIA):
                ruta = store.feed_path(salida, resultado.fund.ticker)
                try:
                    store.write_feed(ruta, resultado.feed)
                except store.FeedError as exc:
                    print(
                        f"[FALLA] {resultado.fund.ticker} no se pudo escribir: {exc}",
                        file=sys.stderr,
                    )
                    error_escritura = True
        for ticker, feed in backfills.items():
            ruta = store.backfill_path(salida, ticker)
            try:
                store.write_feed(ruta, feed)
            except store.FeedError as exc:
                # Un backfill que no se puede escribir no invalida el feed oficial.
                aviso = f"[AVISO] {ticker} backfill no se pudo escribir: {exc}"
                print(aviso)
                lineas_stdout.append(aviso)

        feeds_pagina: dict[str, store.Feed | None] = {}
        for fund in catalog.FUNDS:
            try:
                feeds_pagina[fund.ticker] = store.read_feed(
                    store.feed_path(salida, fund.ticker), fund
                )
            except store.FeedError:
                feeds_pagina[fund.ticker] = None
        try:
            status_page.write(pagina, feeds_pagina, hoy)
        except store.FeedError as exc:
            print(f"[FALLA] página de estado: {exc}", file=sys.stderr)
            error_escritura = True

    _resumen_actions(lineas_stdout)

    if error_escritura:
        return SALIDA_CONFIG
    if todo_fallo:
        return SALIDA_CONFIG
    if any(r.estado is Estado.ANOMALIA for r in resultados):
        return SALIDA_GUARDA
    if any(r.estado is Estado.FALLA for r in resultados):
        return SALIDA_PARCIAL
    return SALIDA_OK
