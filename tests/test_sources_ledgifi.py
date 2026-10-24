"""Fuente A (LedgiFi): tabla de series, cuota y serie de índice."""

from __future__ import annotations

import pytest
from conftest import tabla_ledgifi

from fund_quotes.sources import SourceError, ledgifi


def test_ac01_parsea_la_cuota_del_fixture_real(html_ledgifi):
    quote = ledgifi.parse_quote(html_ledgifi)
    assert quote.date.isoformat() == "2026-10-15"
    assert quote.close == 5054.2279


def test_ac10_parsea_cada_ejemplo_del_esquema():
    casos = [
        ("$5.054,2279", "15 de octubre de 2026", 5054.2279, "2026-10-15"),
        ("$1.234,5", "1 de septiembre de 2026", 1234.5, "2026-09-01"),
        ("$987,6543", "31 de diciembre de 2025", 987.6543, "2025-12-31"),
    ]
    for texto, fecha, cierre, iso in casos:
        quote = ledgifi.parse_quote(tabla_ledgifi(texto, fecha))
        assert quote.close == cierre
        assert quote.date.isoformat() == iso


def test_usa_el_texto_sr_only_y_no_duplica_el_valor():
    # La celda real trae el valor dos veces (sr-only + visual); el parser debe
    # tomar uno solo y no "$5.054,2279$5.054,2279".
    html = tabla_ledgifi("$5.054,2279", "15 de octubre de 2026")
    assert ledgifi.parse_quote(html).close == 5054.2279


def test_ac04_sin_fila_unica_falla_con_motivo_accionable():
    html = tabla_ledgifi(serie="B")
    with pytest.raises(SourceError) as excinfo:
        ledgifi.parse_quote(html)
    assert "no se encontró la cuota de CFMITNIPSA" in str(excinfo.value)


def test_sin_columna_valor_cuota_falla():
    html = "<html><body><table><tr><th>Serie</th></tr><tr><td>UNICA</td></tr></table></body></html>"
    with pytest.raises(SourceError) as excinfo:
        ledgifi.parse_quote(html)
    assert "Valor cuota" in str(excinfo.value)


def test_ac10b_valor_ambiguo_falla_con_error_de_formato():
    html = tabla_ledgifi("1,234.56")
    with pytest.raises(SourceError) as excinfo:
        ledgifi.parse_quote(html)
    assert "formato inválido" in str(excinfo.value)
    assert "ambiguo" in str(excinfo.value)


def test_respuesta_corta_falla():
    with pytest.raises(SourceError):
        ledgifi.parse_quote("<html></html>")


def test_ac11_serie_de_indice_tiene_156_puntos(html_ledgifi):
    indice = ledgifi.parse_index(html_ledgifi)
    assert len(indice) == 156
    assert indice[0].date.isoformat() == "2016-01-01"
    assert indice[-1].date.isoformat() == "2026-10-15"
    assert str(indice[-1].value) == "173.8262101046597"
    assert indice == sorted(indice, key=lambda punto: punto.date)


def test_indice_conserva_precision_completa(html_ledgifi):
    indice = ledgifi.parse_index(html_ledgifi)
    # El índice no se redondea a 4 decimales: se usa como razón del backfill.
    assert len(str(indice[-1].value).split(".")[1]) > 10


def test_indice_ausente_falla():
    with pytest.raises(SourceError) as excinfo:
        ledgifi.parse_index("<html><body>sin serie</body></html>")
    assert "serie de índice" in str(excinfo.value)


def test_cargar_usa_el_modo_markdown_primero(monkeypatch, md_ledgifi):
    llamadas = []

    def falso_fetch(*args, **kwargs):
        llamadas.append(kwargs)
        return md_ledgifi

    monkeypatch.setattr(ledgifi, "fetch_text", falso_fetch)
    quote, indice = ledgifi.cargar()
    assert len(llamadas) == 1
    # El modo primario va sin x-return-format: con esa cabecera jina devuelve el
    # checkpoint de Vercel en lugar de la ficha renderizada.
    assert "headers" not in llamadas[0]
    assert quote.date.isoformat() == "2026-10-22"
    assert quote.close == 4963.6791
    assert indice is None
    assert ledgifi.PROXY_URL.startswith("https://r.jina.ai/https://ledgifi.com/")


def test_cargar_sin_indice_no_lo_parsea(monkeypatch, md_ledgifi):
    monkeypatch.setattr(ledgifi, "fetch_text", lambda *a, **k: md_ledgifi)
    _, indice = ledgifi.cargar()
    assert indice is None


# --- Modo primario: markdown de r.jina.ai ---------------------------------


def test_parsea_la_cuota_del_markdown_real(md_ledgifi):
    quote = ledgifi.parse_quote_markdown(md_ledgifi)
    assert quote.date.isoformat() == "2026-10-22"
    assert quote.close == 4963.6791


def test_markdown_ubica_la_columna_por_encabezado_sin_tac():
    # Variante de la tabla con menos columnas y en otro orden: el índice de
    # 'Valor cuota' cambia, así que no se puede asumir una posición fija.
    markdown = (
        "Markdown Content:\n\n"
        "| Serie | Patrimonio | Valor cuota | Aportantes |\n"
        "| --- | --- | --- | --- |\n"
        "| UNICA condición no publicada | $170.950 M | $4.963,6791 22 de octubre de 2026 | 38 |\n"
        "\n"
        + "relleno " * 140
    )
    quote = ledgifi.parse_quote_markdown(markdown)
    assert quote.date.isoformat() == "2026-10-22"
    assert quote.close == 4963.6791


def test_markdown_con_encabezado_desplazado_y_fila_unica():
    # Separadores con dos guiones y alineación explícita: el encabezado manda.
    markdown = (
        "| Serie | Volatilidad | Valor cuota |\n"
        "| :-- | :-- | --: |\n"
        "| UNICA condición no publicada | 17,2% | $5.054,2279 15 de octubre de 2026 |\n"
        + "relleno " * 140
    )
    quote = ledgifi.parse_quote_markdown(markdown)
    assert quote.date.isoformat() == "2026-10-15"
    assert quote.close == 5054.2279


def test_markdown_encuentra_la_serie_en_la_primera_celda_no_al_principio():
    markdown = (
        "| Serie | Valor cuota |\n| --- | --- |\n"
        "| Serie ÚNICA | $4.963,6791 22 de octubre de 2026 |\n" + "relleno " * 140
    )
    quote = ledgifi.parse_quote_markdown(markdown)
    assert quote.close == 4963.6791


def test_markdown_con_el_checkpoint_de_vercel_falla_con_motivo():
    checkpoint = (
        "Title: Vercel Security Checkpoint\n\n"
        "Markdown Content:\nVercel Security Checkpoint\n" + "x" * 1200
    )
    with pytest.raises(SourceError) as excinfo:
        ledgifi.parse_quote_markdown(checkpoint)
    assert "bloqueo" in str(excinfo.value)
    assert "vercel security checkpoint" in str(excinfo.value).lower()


def test_markdown_demasiado_pequeno_falla():
    with pytest.raises(SourceError) as excinfo:
        ledgifi.parse_quote_markdown("| Serie | Valor cuota |\n| --- | --- |")
    assert "demasiado pequeña" in str(excinfo.value)


def test_markdown_sin_fila_unica_falla():
    markdown = (
        "| Serie | Valor cuota |\n| --- | --- |\n"
        "| B | $1.000,0000 22 de octubre de 2026 |\n" + "relleno " * 140
    )
    with pytest.raises(SourceError) as excinfo:
        ledgifi.parse_quote_markdown(markdown)
    assert "no se encontró la cuota de CFMITNIPSA" in str(excinfo.value)


def test_markdown_sin_columna_valor_cuota_falla():
    markdown = (
        "| Serie | TAC |\n| --- | --- |\n| UNICA | No publicada |\n" + "relleno " * 140
    )
    with pytest.raises(SourceError) as excinfo:
        ledgifi.parse_quote_markdown(markdown)
    assert "Valor cuota" in str(excinfo.value)


def test_markdown_bloqueado_cae_al_modo_html(monkeypatch, html_ledgifi):
    checkpoint = "Title: Vercel Security Checkpoint\n" + "x" * 1200
    llamadas = []

    def falso_fetch(*args, **kwargs):
        llamadas.append(kwargs)
        if kwargs.get("headers") == ledgifi.CABECERAS_HTML:
            return html_ledgifi
        return checkpoint

    monkeypatch.setattr(ledgifi, "fetch_text", falso_fetch)
    quote, indice = ledgifi.cargar()
    assert len(llamadas) == 2
    assert quote.date.isoformat() == "2026-10-15"
    assert quote.close == 5054.2279
    assert indice is None


def test_ambos_modos_bloqueados_falla_con_motivo_accionable(monkeypatch):
    def falso_fetch(*args, **kwargs):
        raise ledgifi.FetchError(
            "la respuesta contiene una página de bloqueo (vercel security checkpoint); "
            "no se intenta evadir el mecanismo del sitio",
            retryable=True,
        )

    monkeypatch.setattr(ledgifi, "fetch_text", falso_fetch)
    with pytest.raises(SourceError) as excinfo:
        ledgifi.cargar()
    motivo = str(excinfo.value)
    assert "modo markdown" in motivo
    assert "modo HTML" in motivo
    assert "vercel security checkpoint" in motivo.lower()


def test_cargar_con_indice_pide_el_html_tras_el_markdown(monkeypatch, md_ledgifi, html_ledgifi):
    llamadas = []

    def falso_fetch(*args, **kwargs):
        llamadas.append(kwargs)
        return html_ledgifi if kwargs.get("headers") == ledgifi.CABECERAS_HTML else md_ledgifi

    monkeypatch.setattr(ledgifi, "fetch_text", falso_fetch)
    quote, indice = ledgifi.cargar(con_indice=True)
    assert len(llamadas) == 2
    assert "headers" not in llamadas[0]
    assert llamadas[1]["headers"] == {"x-return-format": "html"}
    assert quote.date.isoformat() == "2026-10-22"
    # El índice solo existe en el HTML; el último punto del fixture es el 15-10.
    assert indice is not None and indice[-1].date.isoformat() == "2026-10-15"


def test_backfill_degrada_si_el_modo_html_esta_bloqueado(monkeypatch, md_ledgifi):
    def falso_fetch(*args, **kwargs):
        if kwargs.get("headers") == ledgifi.CABECERAS_HTML:
            raise ledgifi.FetchError(
                "respuesta demasiado pequeña (5263 bytes < 10000); posible bloqueo",
                retryable=True,
            )
        return md_ledgifi

    monkeypatch.setattr(ledgifi, "fetch_text", falso_fetch)
    quote, indice = ledgifi.cargar(con_indice=True)
    # La cuota se publica igual; el índice queda en None y el CLI avisa (§5.2).
    assert quote.close == 4963.6791
    assert indice is None
