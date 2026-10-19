"""HTTP acotado: allowlist de hosts, tope de tamaño, timeout y reintentos.

Este módulo no interpreta el contenido de la respuesta; solo lo entrega como
texto. Cualquier host fuera de la allowlist se rechaza antes de emitir la
petición, y una redirección hacia otro dominio se aborta.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request

ALLOWED_HOSTS = frozenset(
    {
        "ledgifi.com",
        "r.jina.ai",
        "aindependencia.cl",
        # El sitio del administrador se sirve con www; se declara explícito en
        # lugar de aceptar cualquier subdominio.
        "www.aindependencia.cl",
    }
)

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_MIN_BYTES = 10_000
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF = (5.0, 15.0)

USER_AGENT = "fund-quotes/1.0 (+https://github.com/ginkelte/fund-quotes)"

_BLOQUEO_MARCAS = (
    "vercel security checkpoint",
    "just a moment",
    "cf-chl",
)

# Estados que se consideran transitorios (se reintentan).
_REINTENTABLES = frozenset({403, 408, 425, 429, 451, 500, 502, 503, 504})


class FetchError(Exception):
    """Falla de adquisición con un motivo accionable en español de Chile."""

    def __init__(self, motivo: str, *, retryable: bool = False) -> None:
        super().__init__(motivo)
        self.motivo = motivo
        self.retryable = retryable


def validar_url(url: str) -> None:
    """Exige HTTPS y un host de la allowlist; lanza ``FetchError`` si no."""

    partes = urllib.parse.urlsplit(url)
    if partes.scheme != "https":
        raise FetchError(f"URL rechazada: se exige https ({url})")
    host = (partes.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise FetchError(
            f"host fuera de la allowlist: {host or '(vacío)'}; "
            f"permitidos: {', '.join(sorted(ALLOWED_HOSTS))}"
        )
    if partes.username or partes.password:
        raise FetchError("URL rechazada: no se permiten credenciales embebidas")


class _RedirectAcotado(urllib.request.HTTPRedirectHandler):
    """Redirecciones solo dentro de la allowlist."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        try:
            validar_url(newurl)
        except FetchError as exc:
            raise FetchError(f"redirección rechazada: {exc.motivo}") from None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _abrir(url: str, headers: dict[str, str], timeout: int, opener):
    peticion = urllib.request.Request(url, headers=headers, method="GET")
    if opener is not None:
        return opener.open(peticion, timeout=timeout)
    manejador = urllib.request.build_opener(_RedirectAcotado)
    return manejador.open(peticion, timeout=timeout)


def _leer_acotado(respuesta, max_bytes: int) -> bytes:
    cuerpo = respuesta.read(max_bytes + 1)
    if len(cuerpo) > max_bytes:
        raise FetchError(
            f"la respuesta supera el tope de {max_bytes // (1024 * 1024)} MB permitido"
        )
    return cuerpo


def _una_peticion(
    url: str,
    headers: dict[str, str],
    timeout: int,
    max_bytes: int,
    min_bytes: int,
    opener,
) -> str:
    try:
        respuesta = _abrir(url, headers, timeout, opener)
        with respuesta:
            estado = getattr(respuesta, "status", 200)
            cuerpo = _leer_acotado(respuesta, max_bytes)
    except urllib.error.HTTPError as exc:
        detalle = ""
        try:
            detalle = exc.read(2048).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - el detalle es best-effort
            detalle = ""
        if "vercel security checkpoint" in detalle.lower():
            raise FetchError(
                f"la fuente respondió con Vercel Security Checkpoint (HTTP {exc.code}); "
                "posible bloqueo del proxy",
                retryable=True,
            ) from None
        if exc.code in _REINTENTABLES:
            raise FetchError(
                f"la fuente respondió HTTP {exc.code}; se reintentará",
                retryable=True,
            ) from None
        raise FetchError(f"la fuente respondió HTTP {exc.code}") from None
    except FetchError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"no se pudo conectar con la fuente: {exc}", retryable=True) from None

    if estado != 200:
        raise FetchError(f"la fuente respondió HTTP {estado}", retryable=estado in _REINTENTABLES)

    if len(cuerpo) < min_bytes:
        raise FetchError(
            f"respuesta demasiado pequeña ({len(cuerpo)} bytes < {min_bytes}); "
            "posible bloqueo o página de error",
            retryable=True,
        )

    texto = cuerpo.decode("utf-8", "replace")
    minusculas = texto.lower()
    for marca in _BLOQUEO_MARCAS:
        if marca in minusculas:
            raise FetchError(
                f"la respuesta contiene una página de bloqueo ({marca}); "
                "no se intenta evadir el mecanismo del sitio",
                retryable=True,
            )
    return texto


def fetch_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    min_bytes: int = DEFAULT_MIN_BYTES,
    retries: int = DEFAULT_RETRIES,
    backoff: tuple[float, ...] = DEFAULT_BACKOFF,
    _sleep=time.sleep,
    _opener=None,
) -> str:
    """Descarga ``url`` como texto con reintentos y validaciones de red.

    ``_sleep`` y ``_opener`` existen para las pruebas (sin red y sin esperas).
    """

    validar_url(url)
    cabeceras = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-CL,es;q=0.9",
    }
    if headers:
        cabeceras.update(headers)

    intentos = max(0, retries) + 1
    ultimo_error: FetchError | None = None
    for intento in range(intentos):
        try:
            return _una_peticion(url, cabeceras, timeout, max_bytes, min_bytes, _opener)
        except FetchError as exc:
            ultimo_error = exc
            if not exc.retryable or intento == intentos - 1:
                raise
            pausa = backoff[min(intento, len(backoff) - 1)]
            _sleep(pausa)

    assert ultimo_error is not None
    raise ultimo_error
