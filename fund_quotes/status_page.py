"""Página de estado autocontenida (sin JS ni assets externos).

Muestra, por fondo, el último cierre, la fecha, la fuente y los días hábiles
transcurridos desde el último punto. Alerta cuando superan 3. No incluye fecha
ni hora de generación: el HTML depende solo de los feeds y de ``hoy``.
"""

from __future__ import annotations

import html
from datetime import date, timedelta
from pathlib import Path

from .catalog import FUNDS, Fund
from .store import Feed

UMBRAL_DIAS_HABILES = 3


def dias_habiles(desde: date, hasta: date) -> int:
    """Días L-V en el intervalo ``(desde, hasta]`` (sin feriados, v1)."""

    if hasta <= desde:
        return 0
    total = 0
    cursor = desde + timedelta(days=1)
    while cursor <= hasta:
        if cursor.weekday() < 5:
            total += 1
        cursor += timedelta(days=1)
    return total


def formato_clp(valor: float) -> str:
    """``5054.2279`` -> ``5.054,2279`` (hasta 4 decimales, mínimo 2)."""

    texto = f"{valor:,.4f}".replace(",", "_").replace(".", ",").replace("_", ".")
    entero, decimales = texto.split(",")
    decimales = decimales.rstrip("0")
    if len(decimales) < 2:
        decimales = (decimales + "00")[:2]
    return f"{entero},{decimales}"


def _fuentes(fund: Fund, efectiva: str) -> str:
    """Fuente efectiva y, si el fondo tiene cadena, las de respaldo configuradas."""

    respaldos = [fuente for fuente in fund.sources if fuente != efectiva]
    if not respaldos:
        return html.escape(efectiva)
    return f"{html.escape(efectiva)} (respaldo: {html.escape(', '.join(respaldos))})"


def _fila(fund: Fund, feed: Feed | None, hoy: date) -> str:
    if feed is None or feed.last is None:
        estado = "Alerta: sin datos publicados"
        return (
            f'      <tr class="alerta">\n'
            f"        <td>{html.escape(fund.name)}</td>\n"
            f"        <td><code>{html.escape(fund.ticker)}</code></td>\n"
            f"        <td>—</td>\n"
            f"        <td>—</td>\n"
            f"        <td>{_fuentes(fund, fund.source)}</td>\n"
            f"        <td>—</td>\n"
            f"        <td>{html.escape(estado)}</td>\n"
            f"      </tr>"
        )

    ultimo = feed.last
    dias = dias_habiles(ultimo.date, hoy)
    if dias > UMBRAL_DIAS_HABILES:
        clase = "alerta"
        estado = f"Alerta: {dias} días hábiles sin actualización (umbral {UMBRAL_DIAS_HABILES})"
    else:
        clase = "al-dia"
        estado = f"Al día: {dias} días hábiles desde el último punto"

    return (
        f'      <tr class="{clase}">\n'
        f"        <td>{html.escape(feed.name)}</td>\n"
        f"        <td><code>{html.escape(feed.ticker)}</code></td>\n"
        f"        <td class=\"num\">{html.escape(formato_clp(ultimo.close))}</td>\n"
        f"        <td>{ultimo.date.isoformat()}</td>\n"
        f"        <td>{_fuentes(fund, feed.source)}</td>\n"
        f"        <td class=\"num\">{dias}</td>\n"
        f"        <td>{html.escape(estado)}</td>\n"
        f"      </tr>"
    )


def render(feeds: dict[str, Feed | None], hoy: date) -> str:
    """HTML completo y determinista para los fondos del catálogo."""

    filas = []
    for fund in FUNDS:
        filas.append(_fila(fund, feeds.get(fund.ticker), hoy))
    cuerpo = "\n".join(filas)
    return f"""<!DOCTYPE html>
<html lang="es-CL">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Estado del feed de cotizaciones</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; padding: 2rem 1.25rem; background: #0d1117; color: #e6edf3;
         font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
  main {{ max-width: 60rem; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 .35rem; }}
  p.sub {{ color: #8b949e; margin: 0 0 1.75rem; font-size: .95rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .95rem; }}
  caption {{ text-align: left; color: #8b949e; padding-bottom: .6rem; }}
  th {{ text-align: left; font-weight: 600; color: #8b949e; border-bottom: 1px solid #30363d;
        padding: .55rem .6rem; font-size: .82rem; text-transform: uppercase; letter-spacing: .04em; }}
  td {{ padding: .65rem .6rem; border-bottom: 1px solid #21262d; vertical-align: top; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  code {{ background: #161b22; border: 1px solid #30363d; border-radius: 4px;
          padding: .1rem .35rem; font-size: .85em; }}
  tr.al-dia td:last-child {{ color: #3fb950; }}
  tr.alerta td:last-child {{ color: #f85149; font-weight: 600; }}
  tr.alerta td {{ background: #1f1113; }}
  footer {{ margin-top: 2rem; color: #8b949e; font-size: .85rem; line-height: 1.6; }}
</style>
</head>
<body>
<main>
  <h1>Estado del feed de cotizaciones</h1>
  <p class="sub">Último punto publicado por fuente, con la antigüedad en días hábiles (lunes a viernes).</p>
  <table>
    <caption>Fondos del catálogo</caption>
    <thead>
      <tr>
        <th scope="col">Fondo</th>
        <th scope="col">Ticker</th>
        <th scope="col">Último cierre</th>
        <th scope="col">Fecha</th>
        <th scope="col">Fuente</th>
        <th scope="col">Días hábiles</th>
        <th scope="col">Estado</th>
      </tr>
    </thead>
    <tbody>
{cuerpo}
    </tbody>
  </table>
  <footer>
    La alerta se activa cuando pasan más de {UMBRAL_DIAS_HABILES} días hábiles desde el último punto.
    Los días hábiles se cuentan de lunes a viernes, sin feriados.
    Los cierres están en pesos chilenos (CLP).
  </footer>
</main>
</body>
</html>
"""


def write(path: str | Path, feeds: dict[str, Feed | None], hoy: date) -> None:
    from .store import write_atomic

    write_atomic(path, render(feeds, hoy).encode("utf-8"))
