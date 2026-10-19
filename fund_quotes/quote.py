"""Modelo de una cotización y normalización del formato numérico chileno.

Formato aceptado (REQ-ADP-003): punto de miles, coma decimal, cuatro decimales
en la fuente. Un valor ambiguo (por ejemplo ``1,234.56``) se rechaza: no se
adivina el separador decimal.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MAX_CLOSE = Decimal("10000000")
_CUATRO_DECIMALES = Decimal("0.0001")

_MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_FECHA_ES = re.compile(r"(\d{1,2})\s+de\s+([a-zA-ZÁÉÍÓÚÜÑáéíóúüñ]+)\s+de\s+(\d{4})")


class QuoteFormatError(ValueError):
    """Valor o fecha con un formato que no se puede normalizar sin adivinar."""


@dataclass(frozen=True)
class Quote:
    """Un punto de la serie: fecha de valorización y cierre en CLP."""

    date: date
    close: float

    def to_dict(self) -> dict:
        return {"date": self.date.isoformat(), "close": self.close}


def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def parse_fecha_es(texto: str) -> date:
    """Convierte ``"15 de octubre de 2026"`` en ``date(2026, 10, 15)``."""

    if not isinstance(texto, str):
        raise QuoteFormatError(f"fecha no textual: {texto!r}")
    coincidencia = _FECHA_ES.search(texto)
    if coincidencia is None:
        raise QuoteFormatError(f"fecha en español no reconocida: {texto!r}")
    dia_txt, mes_txt, anio_txt = coincidencia.groups()
    mes = _MESES.get(_sin_acentos(mes_txt).lower())
    if mes is None:
        raise QuoteFormatError(f"mes desconocido en la fecha: {mes_txt!r}")
    try:
        return date(int(anio_txt), mes, int(dia_txt))
    except ValueError as exc:
        raise QuoteFormatError(f"fecha inválida: {texto!r} ({exc})") from None


def close_desde_decimal(valor: Decimal) -> float:
    """Valida el rango y redondea half-up a 4 decimales."""

    if not valor.is_finite():
        raise QuoteFormatError("el valor no es un número finito")
    if not (Decimal(0) < valor < MAX_CLOSE):
        raise QuoteFormatError(f"valor fuera de rango (0, {MAX_CLOSE}): {valor}")
    return float(valor.quantize(_CUATRO_DECIMALES, rounding=ROUND_HALF_UP))


def normalize_close(bruto: str) -> float:
    """Normaliza ``"$5.054,2279"`` a ``5054.2279`` (REQ-ADP-003)."""

    if not isinstance(bruto, str):
        raise QuoteFormatError(f"valor no textual: {bruto!r}")
    texto = bruto.replace("\u00a0", " ").replace("$", "").strip()
    texto = re.sub(r"\s+", "", texto)
    if not texto:
        raise QuoteFormatError("valor vacío")
    if re.search(r"[eE]", texto):
        raise QuoteFormatError(f"formato no admitido (notación científica): {bruto!r}")
    if not re.fullmatch(r"[0-9.,]+", texto):
        raise QuoteFormatError(f"formato no numérico: {bruto!r}")

    if "," in texto and "." in texto:
        if not re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d+", texto):
            raise QuoteFormatError(
                f"formato ambiguo: {bruto!r}; se exige punto de miles y coma decimal"
            )
        entero, decimales = texto.rsplit(",", 1)
        entero = entero.replace(".", "")
    elif "," in texto:
        if not re.fullmatch(r"\d+,\d+", texto):
            raise QuoteFormatError(f"formato numérico inválido: {bruto!r}")
        entero, decimales = texto.split(",", 1)
    elif "." in texto:
        # Solo puntos: si el último grupo tiene 3 dígitos puede ser un separador
        # de miles sin decimales, y eso es ambiguo -> se rechaza.
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", texto):
            raise QuoteFormatError(
                f"formato ambiguo o sin decimales: {bruto!r}; falta la coma decimal"
            )
        if not re.fullmatch(r"\d+\.\d+", texto):
            raise QuoteFormatError(f"formato numérico inválido: {bruto!r}")
        entero, decimales = texto.split(".", 1)
    else:
        raise QuoteFormatError(
            f"valor sin separador decimal: {bruto!r}; no se acepta un entero"
        )

    try:
        valor = Decimal(f"{entero}.{decimales}")
    except InvalidOperation:
        raise QuoteFormatError(f"valor no convertible: {bruto!r}") from None
    return close_desde_decimal(valor)


def quote_from_texto(bruto: str, fecha_texto: str) -> Quote:
    """Atajo: normaliza valor y fecha en español en un solo paso."""

    return Quote(date=parse_fecha_es(fecha_texto), close=normalize_close(bruto))
