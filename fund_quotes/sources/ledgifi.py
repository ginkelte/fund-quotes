"""Fuente A — LedgiFi, fondo 9019 (CFMITNIPSA, serie UNICA).

El sitio responde 429 con un checkpoint de Vercel si se consulta directo, por lo
que se lee a través de ``r.jina.ai``. Hay dos modos y un orden fijo:

- **Primario, markdown** (sin ``x-return-format``): jina renderiza el JS y pasa
  el challenge, y entrega la tabla de series ya convertida a tabla markdown.
- **Respaldo, HTML** (con ``x-return-format: html``): su fetcher a veces recibe
  la página "Vercel Security Checkpoint"; además es la única fuente de la serie
  de índice que alimenta el ``--backfill``.

La tabla HTML se parsea con ``html.parser`` localizando la columna ``Valor
cuota`` por encabezado; la tabla markdown también se ubica por encabezado (el
número de columnas varía entre variantes), nunca con expresiones regulares
sobre el texto completo.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

from ..fetch import FetchError, fetch_text
from ..quote import Quote, QuoteFormatError, normalize_close, parse_fecha_es
from . import SourceError

URL = "https://ledgifi.com/chile/fondos/fondo/9019"
PROXY_URL = f"https://r.jina.ai/{URL}"
FUENTE = "ledgifi:9019"

ENCABEZADO_VALOR = "valor cuota"
SERIE = "UNICA"

# Modos de lectura del proxy. El markdown va sin cabecera extra a propósito.
CABECERAS_HTML = {"x-return-format": "html"}
MIN_BYTES_MARKDOWN = 1_000
MIN_BYTES_HTML = 10_000

# Firmas de página de bloqueo: si aparecen, el cuerpo no es la ficha del fondo.
_BLOQUEO_MARCAS = (
    "vercel security checkpoint",
    "just a moment",
    "cf-chl",
)

_VACIOS = frozenset({"br", "img", "hr", "input", "meta", "link", "source", "wbr", "col"})

# Pares ("d","v") de la serie de índice embebida en el payload de la página.
# El payload viene escapado dentro de un string de JavaScript, por lo que puede
# haber uno o más backslashes antes de cada comilla.
_PAR_INDICE = re.compile(
    r'\{\\+"d\\+":\\+"(?P<d>\d{4}-\d{2}-\d{2})\\+",\\+"v\\+":\s*'
    r"(?P<v>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\}"
)


@dataclass(frozen=True)
class IndexPoint:
    """Punto de la serie de índice (sin redondear: se usa como razón)."""

    date: date
    value: Decimal


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sin_tildes).strip().lower()


class _Celda:
    __slots__ = ("parte", "partes", "profundidad", "sr", "sr_prof", "tag", "texto")

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.texto = ""
        self.sr = ""
        self.partes: list[str] = []
        self.profundidad = 0
        self.parte: list[str] | None = None
        self.sr_prof = 0


class _TablaParser(HTMLParser):
    """Colecta encabezados y filas de las tablas del documento."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tablas: list[dict] = []
        self._pila: list[dict] = []
        self._fila: list[_Celda] | None = None
        self._celda: _Celda | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._pila.append({"header": [], "rows": []})
            return
        if not self._pila:
            return
        if tag == "tr":
            self._fila = []
        elif tag in ("td", "th"):
            celda = _Celda(tag)
            self._celda = celda
            if self._fila is not None:
                self._fila.append(celda)
        elif tag in _VACIOS:
            return
        elif self._celda is not None:
            celda = self._celda
            celda.profundidad += 1
            if celda.profundidad == 1:
                celda.parte = []
            if tag == "span":
                clases = (dict(attrs).get("class") or "").split()
                if "sr-only" in clases and celda.sr_prof == 0:
                    celda.sr_prof = celda.profundidad

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "table":
            if self._pila:
                self.tablas.append(self._pila.pop())
            return
        if not self._pila:
            return
        if tag in ("td", "th"):
            self._celda = None
        elif tag == "tr":
            if self._fila is not None:
                tabla = self._pila[-1]
                if any(celda.tag == "th" for celda in self._fila):
                    tabla["header"] = [celda.texto.strip() for celda in self._fila]
                elif self._fila:
                    tabla["rows"].append(self._fila)
            self._fila = None
        elif tag in _VACIOS:
            return
        elif self._celda is not None:
            celda = self._celda
            if tag == "span" and celda.sr_prof == celda.profundidad:
                celda.sr_prof = 0
            if celda.profundidad == 1 and celda.parte is not None:
                celda.partes.append("".join(celda.parte))
                celda.parte = None
            celda.profundidad = max(0, celda.profundidad - 1)

    def handle_data(self, data):
        celda = self._celda
        if celda is None:
            return
        celda.texto += data
        if celda.parte is not None:
            celda.parte.append(data)
        if 0 < celda.sr_prof <= celda.profundidad:
            celda.sr += data


def _tabla_de_series(html: str) -> dict:
    parser = _TablaParser()
    parser.feed(html)
    parser.close()
    for tabla in parser.tablas:
        cabecera = [_normalizar(celda) for celda in tabla["header"]]
        if ENCABEZADO_VALOR in cabecera:
            return tabla
    raise SourceError(
        "no se encontró la cuota de CFMITNIPSA: la tabla de series de LedgiFi "
        f"no tiene la columna 'Valor cuota' (posible cambio de layout en {URL})"
    )


def _valor_de_celda(celda: _Celda) -> str:
    """Prefiere el texto para lectores de pantalla, que trae el valor completo."""

    if celda.sr.strip():
        return celda.sr.strip()
    candidatos = [
        parte.strip()
        for parte in celda.partes
        if parte.strip() and re.fullmatch(r"\$?\s*[\d.,]+", parte.strip())
    ]
    if candidatos:
        return max(candidatos, key=len)
    coincidencia = re.search(r"\$?\s*\d[\d.,]*", celda.texto)
    if coincidencia:
        return coincidencia.group(0).strip()
    return celda.texto.strip()


def _fecha_de_celda(celda: _Celda):
    """Busca la fecha en cada span de la celda antes de usar el texto concatenado.

    La celda de ``Valor cuota`` trae el precio dos veces (sr-only + visual) y la
    fecha en un span aparte; parsear el texto completo puede pegar el precio con
    el día (``...,51 de septiembre``). Por eso se prueban los spans uno a uno.
    """

    for parte in reversed(celda.partes):
        texto = parte.strip()
        if not texto or "$" in texto:
            continue
        try:
            return parse_fecha_es(texto)
        except QuoteFormatError:
            continue
    return parse_fecha_es(celda.texto)


def parse_quote(html: str) -> Quote:
    """Extrae la cuota de la serie UNICA con la fecha publicada por la fuente."""

    if not isinstance(html, str) or len(html) < 60:
        raise SourceError("la respuesta de LedgiFi está vacía o es demasiado corta")

    tabla = _tabla_de_series(html)
    cabecera = [_normalizar(celda) for celda in tabla["header"]]
    columna = cabecera.index(ENCABEZADO_VALOR)

    fila_serie = None
    for fila in tabla["rows"]:
        if len(fila) <= columna:
            continue
        if _normalizar(fila[0].texto).startswith("unica"):
            fila_serie = fila
            break

    if fila_serie is None:
        raise SourceError(
            "no se encontró la cuota de CFMITNIPSA: la tabla de LedgiFi no trae la "
            f"fila de la serie {SERIE} con 'Valor cuota' (posible cambio de layout)"
        )

    celda = fila_serie[columna]
    texto_valor = _valor_de_celda(celda)
    try:
        cierre = normalize_close(texto_valor)
    except QuoteFormatError as exc:
        raise SourceError(
            f"no se encontró la cuota de CFMITNIPSA: valor con formato inválido "
            f"({texto_valor!r}): {exc}"
        ) from None

    try:
        fecha = _fecha_de_celda(celda)
    except QuoteFormatError as exc:
        raise SourceError(f"no se encontró la fecha de la cuota de CFMITNIPSA: {exc}") from None

    return Quote(date=fecha, close=cierre)


def _celdas_markdown(linea: str) -> list[str]:
    """Separa una fila markdown ``| a | b |`` en celdas sin los delimitadores."""

    texto = linea.strip().removeprefix("|").removesuffix("|")
    return [celda.strip() for celda in texto.split("|")]


def _es_separador(celdas: list[str]) -> bool:
    """Fila de guiones que markdown intercala entre encabezado y cuerpo."""

    return bool(celdas) and all(re.fullmatch(r":?-+:?", celda) for celda in celdas)


_SERIE_UNICA = re.compile(r"\bunica\b")


def _es_fila_unica(celdas: list[str]) -> bool:
    """La fila de la serie pedida: la primera celda nombra la serie ``UNICA``."""

    return bool(celdas) and _SERIE_UNICA.search(_normalizar(celdas[0])) is not None


def _bloqueo_markdown(markdown: str) -> str | None:
    """Devuelve la marca de bloqueo encontrada, si el cuerpo no es la ficha."""

    minusculas = markdown.lower()
    for marca in _BLOQUEO_MARCAS:
        if marca in minusculas:
            return marca
    return None


def parse_quote_markdown(markdown: str) -> Quote:
    """Extrae la cuota de la tabla markdown que entrega jina en modo primario.

    El valor viene en la misma celda que la fecha (``$4.963,6791 22 de octubre de
    2026``) y el número de columnas varía entre variantes de la tabla, por lo que
    la columna se ubica por el encabezado ``Valor cuota`` y nunca por posición
    fija.
    """

    if not isinstance(markdown, str) or not markdown.strip():
        raise SourceError("la respuesta de LedgiFi en modo markdown está vacía")

    marca = _bloqueo_markdown(markdown)
    if marca is not None:
        raise SourceError(
            "la respuesta de LedgiFi en modo markdown es una página de bloqueo "
            f"({marca}); el challenge de Vercel no se resolvió"
        )

    tamano = len(markdown.encode("utf-8"))
    if tamano < MIN_BYTES_MARKDOWN:
        raise SourceError(
            f"la respuesta de LedgiFi en modo markdown es demasiado pequeña "
            f"({tamano} bytes < {MIN_BYTES_MARKDOWN}); posible página de error"
        )

    columna: int | None = None
    fila_serie: list[str] | None = None
    for linea in markdown.splitlines():
        if not linea.strip().startswith("|"):
            continue
        celdas = _celdas_markdown(linea)
        if _es_separador(celdas):
            continue
        normalizadas = [_normalizar(celda) for celda in celdas]
        if columna is None:
            if ENCABEZADO_VALOR in normalizadas:
                columna = normalizadas.index(ENCABEZADO_VALOR)
            continue
        if _es_fila_unica(celdas):
            fila_serie = celdas
            break

    if columna is None:
        raise SourceError(
            "no se encontró la cuota de CFMITNIPSA: la tabla markdown de LedgiFi "
            f"no tiene la columna 'Valor cuota' (posible cambio de layout en {URL})"
        )
    if fila_serie is None or len(fila_serie) <= columna:
        raise SourceError(
            "no se encontró la cuota de CFMITNIPSA: la tabla markdown de LedgiFi no "
            f"trae la fila de la serie {SERIE} con 'Valor cuota' (posible cambio de layout)"
        )

    celda = fila_serie[columna]
    coincidencia = re.search(r"\$?\s*\d[\d.,]*", celda)
    if coincidencia is None:
        raise SourceError(
            "no se encontró la cuota de CFMITNIPSA: la celda 'Valor cuota' del modo "
            f"markdown no trae un número ({celda!r})"
        )
    texto_valor = coincidencia.group(0).strip()
    try:
        cierre = normalize_close(texto_valor)
    except QuoteFormatError as exc:
        raise SourceError(
            f"no se encontró la cuota de CFMITNIPSA: valor con formato inválido "
            f"({texto_valor!r}): {exc}"
        ) from None

    try:
        fecha = parse_fecha_es(celda)
    except QuoteFormatError as exc:
        raise SourceError(f"no se encontró la fecha de la cuota de CFMITNIPSA: {exc}") from None

    return Quote(date=fecha, close=cierre)


def parse_index(html: str) -> list[IndexPoint]:
    """Serie de índice semimensual embebida (base 100 al 2016-01-01).

    No es una cotización oficial: solo alimenta el backfill derivado. Se
    conserva la precisión completa del índice porque se usa como razón.
    """

    if not isinstance(html, str) or not html:
        raise SourceError("la respuesta de LedgiFi está vacía: no hay serie de índice")

    acumulado: dict[str, Decimal] = {}
    for coincidencia in _PAR_INDICE.finditer(html):
        try:
            valor = Decimal(coincidencia.group("v"))
        except InvalidOperation:
            continue
        if not valor.is_finite() or valor <= 0:
            continue
        acumulado[coincidencia.group("d")] = valor

    if len(acumulado) < 2:
        raise SourceError(
            "no se encontró la serie de índice de LedgiFi (pares fecha/índice); "
            "el backfill derivado no está disponible"
        )

    puntos: list[IndexPoint] = []
    for fecha_txt in sorted(acumulado):
        try:
            fecha = date.fromisoformat(fecha_txt)
        except ValueError:
            continue
        puntos.append(IndexPoint(date=fecha, value=acumulado[fecha_txt]))
    if len(puntos) < 2:
        raise SourceError("la serie de índice de LedgiFi no tiene puntos utilizables")
    return puntos


def cargar(con_indice: bool = False) -> tuple[Quote, list[IndexPoint] | None]:
    """Cuota por el modo markdown y respaldo HTML; el índice solo vive en el HTML.

    Precedencia (§4.1): primero markdown (jina renderiza el JS y pasa el
    challenge de Vercel); si ese cuerpo es una página de bloqueo, es demasiado
    pequeño o no trae la fila ``UNICA``, se intenta el modo HTML. Si ambos modos
    fallan se lanza ``SourceError`` con lo que devolvió cada uno.

    La serie de índice para ``--backfill`` sigue viniendo del modo HTML: si ese
    modo está bloqueado, el índice queda en ``None`` y el CLI degrada el backfill
    a un aviso no bloqueante (§5.2).
    """

    motivos: list[str] = []

    # 1) Modo primario: markdown, sin x-return-format.
    quote: Quote | None = None
    try:
        markdown = fetch_text(PROXY_URL, min_bytes=MIN_BYTES_MARKDOWN)
    except FetchError as exc:
        motivos.append(f"modo markdown: {exc.motivo}")
    else:
        try:
            quote = parse_quote_markdown(markdown)
        except SourceError as exc:
            motivos.append(f"modo markdown: {exc}")

    # 2) Modo de respaldo: HTML. También se pide si hace falta el índice.
    html: str | None = None
    if quote is None or con_indice:
        try:
            html = fetch_text(PROXY_URL, headers=CABECERAS_HTML, min_bytes=MIN_BYTES_HTML)
        except FetchError as exc:
            motivos.append(f"modo HTML: {exc.motivo}")
        else:
            if quote is None:
                try:
                    quote = parse_quote(html)
                except SourceError as exc:
                    motivos.append(f"modo HTML: {exc}")

    if quote is None:
        raise SourceError(
            "no se pudo obtener la cuota de CFMITNIPSA: se intentó el modo markdown "
            f"y el modo HTML del proxy; {'; '.join(motivos)}"
        )

    indice = None
    if con_indice and html:
        try:
            indice = parse_index(html)
        except SourceError:
            indice = None
    return quote, indice
