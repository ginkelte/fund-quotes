"""Adaptadores de fuente.

Cada adaptador devuelve un :class:`fund_quotes.quote.Quote` o lanza
``SourceError`` con un motivo accionable. Nunca escribe en disco ni conoce el
formato de los archivos publicados.
"""


class SourceError(Exception):
    """La fuente no entregó la cuota esperada; el motivo es accionable."""
