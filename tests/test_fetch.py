"""REQ-SEC-003 / EC-005: allowlist, redirecciones, tope de tamaño y bloqueos."""

from __future__ import annotations

import email.message
import io
import urllib.error
import urllib.request

import pytest

from fund_quotes.fetch import FetchError, fetch_text, validar_url


class Respuesta:
    status = 200

    def __init__(self, cuerpo: bytes) -> None:
        self._cuerpo = cuerpo

    def read(self, cantidad: int = -1) -> bytes:
        return self._cuerpo if cantidad < 0 else self._cuerpo[:cantidad]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Opener:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas: list[str] = []

    def open(self, peticion, timeout=None):
        self.llamadas.append(peticion.full_url)
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


def http_error(codigo: int, cuerpo: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://ledgifi.com/x", codigo, "error", email.message.Message(), io.BytesIO(cuerpo)
    )


def test_host_fuera_de_allowlist_falla_sin_peticion():
    opener = Opener([Respuesta(b"x" * 20_000)])
    with pytest.raises(FetchError) as excinfo:
        fetch_text("https://example.com/fondos", _opener=opener, _sleep=lambda _s: None)
    assert "allowlist" in str(excinfo.value)
    assert opener.llamadas == []


def test_exige_https():
    with pytest.raises(FetchError) as excinfo:
        fetch_text("http://ledgifi.com/chile/fondos/fondo/9019", _sleep=lambda _s: None)
    assert "https" in str(excinfo.value)


def test_url_con_credenciales_se_rechaza():
    with pytest.raises(FetchError):
        validar_url("https://usuario:clave@ledgifi.com/x")


def test_redireccion_a_otro_dominio_se_rechaza():
    from fund_quotes.fetch import _RedirectAcotado

    manejador = _RedirectAcotado()
    with pytest.raises(FetchError) as excinfo:
        manejador.redirect_request(
            urllib.request.Request("https://ledgifi.com/x"),
            None,
            302,
            "Found",
            email.message.Message(),
            "https://evil.example/robo",
        )
    assert "redirección rechazada" in str(excinfo.value)


def test_redireccion_dentro_de_la_allowlist_se_permite():
    from fund_quotes.fetch import _RedirectAcotado

    manejador = _RedirectAcotado()
    peticion = manejador.redirect_request(
        urllib.request.Request("https://ledgifi.com/x"),
        None,
        302,
        "Found",
        email.message.Message(),
        "https://ledgifi.com/otra",
    )
    assert peticion is not None


def test_ac05_429_con_checkpoint_reintenta_tres_veces_y_falla():
    cuerpo = b"<html>Vercel Security Checkpoint</html>"
    opener = Opener([http_error(429, cuerpo), http_error(429, cuerpo), http_error(429, cuerpo)])
    esperas: list[float] = []
    with pytest.raises(FetchError) as excinfo:
        fetch_text(
            "https://r.jina.ai/https://ledgifi.com/chile/fondos/fondo/9019",
            _opener=opener,
            _sleep=esperas.append,
        )
    assert len(opener.llamadas) == 3
    assert esperas == [5.0, 15.0]
    assert "429" in str(excinfo.value)


def test_ec005_cuerpo_pequeno_se_trata_como_bloqueo():
    opener = Opener([Respuesta(b"<html>corto</html>")] * 3)
    with pytest.raises(FetchError) as excinfo:
        fetch_text("https://www.aindependencia.cl/fondos/", _opener=opener, _sleep=lambda _s: None)
    assert len(opener.llamadas) == 3
    assert "demasiado pequeña" in str(excinfo.value)


def test_ec005_pagina_de_bloqueo_con_status_200():
    opener = Opener([Respuesta(b"<html>Just a moment...</html>" + b" " * 20_000)])
    with pytest.raises(FetchError) as excinfo:
        fetch_text(
            "https://www.aindependencia.cl/fondos/",
            _opener=opener,
            retries=0,
            _sleep=lambda _s: None,
        )
    assert "bloqueo" in str(excinfo.value)


def test_excede_el_tope_de_tamano():
    opener = Opener([Respuesta(b"x" * 2049)])
    with pytest.raises(FetchError) as excinfo:
        fetch_text(
            "https://www.aindependencia.cl/fondos/",
            _opener=opener,
            max_bytes=2048,
            min_bytes=1,
            retries=0,
            _sleep=lambda _s: None,
        )
    assert "tope" in str(excinfo.value)


def test_reintenta_un_error_de_red_y_luego_acepta():
    opener = Opener([urllib.error.URLError("sin ruta"), Respuesta(b"ok" * 10)])
    texto = fetch_text(
        "https://www.aindependencia.cl/fondos/",
        _opener=opener,
        min_bytes=1,
        _sleep=lambda _s: None,
    )
    assert texto == "ok" * 10
    assert len(opener.llamadas) == 2


def test_no_reintenta_un_404():
    opener = Opener([http_error(404)])
    with pytest.raises(FetchError):
        fetch_text("https://www.aindependencia.cl/fondos/", _opener=opener, _sleep=lambda _s: None)
    assert len(opener.llamadas) == 1


def test_envia_user_agent_y_no_cookies():
    opener = Opener([Respuesta(b"ok" * 10)])

    capturado = {}

    class OpenerEspia(Opener):
        def open(self, peticion, timeout=None):
            capturado.update(dict(peticion.header_items()))
            return super().open(peticion, timeout)

    fetch_text(
        "https://www.aindependencia.cl/fondos/",
        _opener=OpenerEspia([Respuesta(b"ok" * 10)]),
        min_bytes=1,
        _sleep=lambda _s: None,
    )
    claves = {clave.lower() for clave in capturado}
    assert "user-agent" in claves
    assert "cookie" not in claves
