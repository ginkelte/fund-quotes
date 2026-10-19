# fund-quotes

Feed estático de cotizaciones diarias de dos fondos chilenos, publicado en GitHub Pages como JSON
que Portfolio Performance consume con su proveedor nativo **JSON**. Sin servidores, sin secretos y
sin dependencias pagas.

## Qué es

Dos archivos JSON con la serie de cuotas de cada fondo:

| Fondo | Ticker | RUN | Fuente |
|---|---|---|---|
| FM IT NOW S&P IPSA (Itaú AGF) | `CFMITNIPSA` | 9019-0 | LedgiFi (`ledgifi.com/chile/fondos/fondo/9019`) |
| FI Independencia Rentas Inmobiliarias | `CFINRENTAS` | 7014-9 | Administradora Independencia (`aindependencia.cl/fondos/`) |

- Feed: `https://ginkelte.github.io/fund-quotes/quotes/CFMITNIPSA.json` y
  `https://ginkelte.github.io/fund-quotes/quotes/CFINRENTAS.json`
- Estado: `https://ginkelte.github.io/fund-quotes/`

Formato de cada archivo:

```json
{
  "ticker": "CFMITNIPSA",
  "name": "FM IT NOW S&P IPSA",
  "currency": "CLP",
  "source": "ledgifi:9019",
  "updated": "2026-10-15",
  "data": [
    {"date": "2026-10-15", "close": 5054.2279}
  ]
}
```

`updated` es la fecha del último punto publicado, no la fecha de ejecución.

## Por qué existe

Portfolio Performance obtenía ambas series desde Yahoo Finance (`CFMITNIPSA.SN`, `CFINRENTAS.SN`).
Desde el **17 de julio de 2026** Yahoo dejó de actualizar las dos series: repite el mismo valor en
todos los días hábiles posteriores, así que la valorización de la cartera quedó congelada en
pantalla. El 15 de octubre de 2026 las fuentes publicaban 5.054,2279 para `CFMITNIPSA`, mientras
Yahoo seguía repitiendo 5.035,3999.

Este repositorio toma la cuota directamente de las fuentes públicas de cada administradora y publica
un feed propio, de modo que la actualización ya no depende de Yahoo.

## Cómo se actualiza

Una GitHub Action (`.github/workflows/daily.yml`) corre **de lunes a viernes a las 22:30 UTC**
(después del cierre de los fondos en Chile). También se puede lanzar a mano desde la pestaña
*Actions* → *Cotizaciones diarias* → *Run workflow*.

El workflow, en orden: instala Python 3.11 y `pytest`, corre la suite, actualiza el feed, commitea y
publica **solo si hay diferencias** en `docs/`, y recién al final falla el job si el feed terminó con
código distinto de 0. Un fondo caído no impide publicar el otro: el commit de los fondos exitosos
ocurre antes de propagar el error.

Para correrlo a mano en local:

```bash
python3 -m fund_quotes --out docs/quotes --status-page docs/index.html
```

Flags disponibles:

| Flag | Para qué sirve |
|---|---|
| `--fondo TICKER [TICKER ...]` | Limita la corrida a uno o más fondos del catálogo (por defecto, ambos) |
| `--dry-run` | Calcula, valida y reporta sin escribir ningún archivo |
| `--backfill N` | Genera N puntos derivados del índice en `<TICKER>.backfill.json` (solo `CFMITNIPSA`; `1 ≤ N ≤ 155`) |
| `--today YYYY-MM-DD` | Fecha de referencia para la página de estado y las validaciones (por defecto, hoy en `America/Santiago`) |
| `--force-anomaly` | Acepta un salto diario mayor a 5,00%, dejando registro del forzado |
| `--out DIR` / `--status-page ARCHIVO` | Cambian las rutas de salida (por defecto `docs/quotes` y `docs/index.html`) |

Códigos de salida: `0` todo al día · `2` éxito parcial (un fondo publicado y otro fallido) ·
`3` punto rechazado por la guarda de anomalía · `1` error de configuración, feed ilegible o todos
los fondos fallidos.

Cada corrida imprime una línea por fondo, por ejemplo:

```
[OK] CFMITNIPSA fecha=2026-10-15 close=5054.2279 fuente=ledgifi:9019
[OK] CFINRENTAS fecha=2026-10-15 close=2181.18 fuente=aindependencia:bolsa
```

## Configuración en Portfolio Performance

Se usa el proveedor **JSON** nativo (no requiere plugins). Se hace una vez por instrumento.

1. **Ticker del instrumento.** Editar el instrumento y dejar el ticker exactamente como
   `CFMITNIPSA` o `CFINRENTAS`, **sin** el sufijo `.SN`. El macro `{TICKER}` se sustituye literal en
   la URL, así que `CFMITNIPSA.SN` apuntaría a un archivo que no existe.
2. **Proveedor de cotizaciones.** En la pestaña de cotizaciones del instrumento, elegir el proveedor
   **JSON** (JSON Quote Feed).
3. **URL.** En el campo de la URL, con el macro incluido:

   ```
   https://ginkelte.github.io/fund-quotes/quotes/{TICKER}.json
   ```

4. **Path to Date**: `$.data[*].date`
5. **Path to Close**: `$.data[*].close`
6. **Moneda**: `CLP` (el feed la declara, pero conviene que el instrumento también la tenga).
7. Guardar y usar **Online → Update quotes** (o *Actualizar cotizaciones*) en el instrumento.

Para verificar que la actualización ocurrió:

- En PP, abrir la vista de cotizaciones del instrumento y confirmar que el último precio coincide con
  el último `close` del JSON (Ctrl+F5 en el navegador para ver el archivo publicado).
- Comparar la fecha del último punto con la fecha del feed: deben ser iguales, y no la fecha de hoy.
- Si PP muestra el mismo valor que antes, revisar que el ticker no tenga `.SN` y que la URL no tenga
  espacios ni un `{TICKER}` mal escrito.
- La página de estado indica la fecha del último punto de cada fondo y los días hábiles transcurridos.

## Migración única desde Yahoo

Portfolio Performance **no sobrescribe** precios históricos ya guardados: si se cambia el proveedor
sin limpiar, las cotizaciones congeladas de Yahoo se quedan en la base y el gráfico sigue plano. Hay
que borrarlas una vez, por instrumento:

1. Abrir el instrumento y ir a la vista de cotizaciones históricas.
2. Seleccionar y **borrar** todas las cotizaciones del rango **2026-07-17 → 2026-10-16** (el tramo en
   que Yahoo repite el mismo valor). No tocar nada anterior al 2026-07-17.
3. Repetir en el otro instrumento.
4. Con el proveedor JSON ya configurado, ejecutar **Online → Update quotes**. El feed repone el tramo
   con los valores reales publicados por cada administradora.

Para `CFINRENTAS` existe además un CSV con las 92 cotizaciones reales de ese rango, por si se prefiere
importarlas a mano en vez de esperar la descarga del feed (lo entrega el orquestador junto con este
cambio). No es necesario si el paso 4 funciona.

## Estado del feed

`https://ginkelte.github.io/fund-quotes/` muestra, por fondo: último cierre, fecha, fuente y días
hábiles transcurridos desde el último punto, con alerta visual cuando supera **3 días hábiles**
(lunes a viernes; v1 no considera feriados).

## Límites

- **No corrige historia pasada**: el feed solo agrega puntos nuevos; nunca reescribe ni reordena lo ya
  publicado. Si una fuente publica un valor distinto para una fecha ya guardada, se conserva el valor
  existente y se avisa por stdout.
- **`--backfill` es una aproximación**: los puntos derivados se calculan como
  `close_conocido × índice(d) / índice(último)`, viven en `<TICKER>.backfill.json` y **no** se mezclan
  con el feed oficial. No son cuotas publicadas y no deberían usarse para valorizar la cartera.
- Un salto diario mayor a 5,00% se rechaza salvo `--force-anomaly`.
- Solo dos fondos, solo pesos chilenos (`CLP`), solo las fuentes documentadas en
  `specs/fund-quotes.spec.md`.

## Estructura del repositorio

```
fund-quotes/
├── fund_quotes/
│   ├── __main__.py           # entrada: python -m fund_quotes
│   ├── cli.py                # flags, orquestación por fondo, códigos de salida
│   ├── catalog.py            # los dos fondos: ticker, nombre, RUN, fuente y URL
│   ├── fetch.py              # HTTP con timeout, tope de tamaño, allowlist y reintentos
│   ├── quote.py              # Quote(fecha, close) y normalización numérica chilena
│   ├── store.py              # merge append-only, serialización determinista, escritura atómica
│   ├── guards.py             # anomalía >5%, fechas implausibles, feed corrupto
│   ├── status_page.py        # docs/index.html autocontenido
│   └── sources/
│       ├── ledgifi.py        # CFMITNIPSA (serie UNICA) + índice para el backfill
│       └── aindependencia.py # CFINRENTAS (serie BOLSA, fecha en UTC)
├── docs/
│   ├── index.html            # generado: página de estado
│   └── quotes/<TICKER>.json  # generado: feed que consume Portfolio Performance
├── specs/                    # spec y escenarios Gherkin aprobados
├── tests/                    # suite sin red, con fixtures en tests/fixtures/
└── .github/workflows/daily.yml
```

GitHub Pages publica desde la rama `main`, carpeta `/docs`.

## Tests

```bash
python3 -m pytest -q
```

La suite corre sin red: todo el parseo se prueba contra los HTML guardados en `tests/fixtures/`.
Producción usa solo la stdlib de Python 3.11; `pytest` es la única dependencia de desarrollo.
