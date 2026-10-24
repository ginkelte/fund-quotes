"""Adaptadores de fuente.

Cada adaptador devuelve ``(list[Quote], indice)`` o lanza ``SourceError`` con un
motivo accionable. La lista viene **ascendente por fecha** y contiene todos los
puntos que la fuente traiga: la serie completa en dividendera (2400+ cierres
desde 2017) y un solo punto en LedgiFi e Independencia, que solo publican el
último valor. El recorte (catch-up, siembra) lo decide el store.

Nunca escribe en disco ni conoce el formato de los archivos publicados.
"""


class SourceError(Exception):
    """La fuente no entregó la cuota esperada; el motivo es accionable."""
