---
spec-id: fund-quotes
id: fund-quotes
title: Feed de cotizaciones diarias para dos fondos chilenos
status: draft
version: 1.0.0
layer: data
tags: [cotizaciones, fondos, chile, portfolio-performance, github-pages, append-only]
acceptance: specs/fund-quotes.feature
owner: Vichoko
created: 2026-10-19
updated: 2026-10-19
---

# Feed de cotizaciones diarias — dos fondos chilenos

## 1. Contexto

Portfolio Performance (PP) obtiene las cotizaciones de dos fondos chilenos desde Yahoo Finance.
Desde el **17 de julio de 2026** Yahoo dejó de actualizar ambas series: repite el mismo valor en
todos los días hábiles posteriores, por lo que PP muestra precios planos y la valorización de la
cartera queda desactualizada. El valor que publican las fuentes el 15 de octubre de 2026
(5.054,2279 para CFMITNIPSA) es distinto del que Yahoo sigue repitiendo (5.035,3999).

| Instrumento | Símbolo Yahoo (histórico, congelado) | Ticker en PP (nuevo) | RUN (público) | Tipo CMF | Estado en Yahoo (verificado 2026-10-18) |
|---|---|---|---|---|---|
| FM IT NOW S&P IPSA (Itaú AGF) | `CFMITNIPSA.SN` | `CFMITNIPSA` | 9019-0 | RGFMU | Serie congelada desde 2026-07-17: repite 5035,3999 todos los días hábiles hasta 2026-10-16 |
| FI Independencia Rentas Inmobiliarias | `CFINRENTAS.SN` | `CFINRENTAS` | 7014-9 | FINRE | Serie congelada desde 2026-07-17: repite 2183,5600 |

Hoy no existe ningún componente propio: la única fuente de precios es Yahoo, dentro de PP. No hay
feed, ni respaldo, ni forma de detectar que la serie dejó de moverse.

## 2. Objetivo

Publicar un **feed estático de cotizaciones diarias** en GitHub Pages, en el formato que consume el
proveedor nativo *JSON Quote Feed* de Portfolio Performance, alimentado por las dos fuentes públicas
verificadas de cada fondo, sin secretos ni dependencias pagas.

Criterio de éxito: PP actualiza ambos instrumentos con la cuota del último día publicado por la
fuente, y el feed conserva toda la historia previa sin duplicados ni puntos inventados.

## 3. Alcance

**Dentro del alcance**

- Dos adaptadores de fuente (uno por fondo), con parseo verificado contra fixtures guardados.
- Un *store* append-only que acumula puntos y escribe de forma atómica.
- Una guarda de anomalías (>5% diario) con override explícito.
- Un publicador de los JSON en `docs/quotes/` y de una página de estado en `docs/index.html`.
- Un CLI con códigos de salida estables y reporte por fuente.
- Tests sin red, con fixtures, y un workflow diario de GitHub Actions.
- Documentación de configuración en PP (README, escrito en la etapa de implementación).

**Fuera del alcance** — ver §11.

## 4. Fuentes de datos

Solo se usan las dos fuentes verificadas. Cualquier URL nueva debe entrar a este documento como
hipótesis explícita antes de implementarse.

| # | Fondo | URL | Selector de parseo | Formato numérico / fecha | Riesgo | Fallback |
|---|---|---|---|---|---|---|
| A | CFMITNIPSA | `https://ledgifi.com/chile/fondos/fondo/9019` leída vía `https://r.jina.ai/<URL>` con header `x-return-format: html` | Fila de la tabla de series cuyo nombre de serie es `UNICA`/`ÚNICA`; columna `Valor cuota`. Fecha en el texto de actualización de la tabla (`"15 de octubre de 2026"`) | `$5.054,2279` → punto de miles, coma decimal, 4 decimales. Fecha en español, día-mes-año | HTTP directo responde **429 + "Vercel Security Checkpoint"** (challenge JS). Riesgo de cambio de layout, de rate limit del proxy o de caída del proxy | 2 reintentos con backoff (5 s, 15 s) vía proxy. Si persiste: el fondo falla ruidosamente, no se escribe punto. Sin fuente oficial alternativa verificada |
| B | CFINRENTAS | `https://www.aindependencia.cl/fondos/` (HTTP 200, HTML plano, ~334 KB) | JS inline `window.vfiChartData = {...}`; serie `"BOLSA"`; último par `[epoch_ms, precio]` | Precio flotante de 2 decimales. `epoch_ms` en **UTC** (ver §4.2) | Rediseño del sitio o cambio de nombre/forma de la serie; la serie `"Valor Libro"` tiene otra escala y no debe usarse | 2 reintentos con backoff. Si falta la serie `"BOLSA"`: el fondo falla ruidosamente, no se escribe punto |

### 4.1 Fuente A — LedgiFi (CFMITNIPSA, RUN 9019-0)

- El HTML pesado (~500 KB) se obtiene con `x-return-format: html` para no depender del markdown.
- El parseo se hace con `html.parser.HTMLParser` (stdlib) sobre las filas de tabla, localizando el
  encabezado `Valor cuota` por índice de columna; **no** se usan expresiones regulares sobre texto
  plano para la tabla. Si no existe la fila de la serie `UNICA`, el adaptador lanza error.
- Las demás series del fondo (si existieran) se ignoran: el instrumento en PP es la serie única.
- La página embebe además una serie histórica semimensual en el HTML: pares
  `{"d":"YYYY-MM-DD","v":<índice>}` con base 100 al 2016-01-01 y 156 puntos (último
  `2026-10-15` = `173.8262101046597`). Esa serie **no es una cotización oficial**: solo se usa para
  el backfill derivado de §6 (`REQ-ADP-004`), en un archivo separado.

### 4.2 Fuente B — Independencia (CFINRENTAS, RUN 7014-9)

- Se extrae el objeto JSON inline con `re` + `json.loads`; nunca se evalúa JavaScript.
- Se elige la serie cuyo `name` es exactamente `BOLSA` (comparación sin distinguir mayúsculas ni
  espacios). Se toma el punto de mayor `epoch_ms`. La serie `Valor Libro` se descarta: está en otra
  escala (≈238,947, frente a ≈2.181 de la cuota) y no representa el precio de la cuota.
- **La fecha se deriva en UTC, no en hora de Chile.** Evidencia verificada: `1792022400000` es
  `2026-10-15T00:00:00Z` y corresponde al punto del 15-10-2026. Convertirlo a `America/Santiago`
  lo desplazaría al 14-10-2026 (21:00 del día anterior). Regla: `datetime.fromtimestamp(ms/1000,
  tz=timezone.utc).date()`.

## 5. Contrato de datos

### 5.1 Archivo publicado: `docs/quotes/<TICKER>.json`

```json
{
  "ticker": "CFMITNIPSA",
  "name": "FM IT NOW S&P IPSA",
  "currency": "CLP",
  "source": "ledgifi:9019",
  "updated": "2026-10-15",
  "data": [
    {"date": "2026-10-14", "close": 5054.0853},
    {"date": "2026-10-15", "close": 5054.2279}
  ]
}
```

Reglas normativas:

1. `ticker` sin sufijo de mercado (`CFMITNIPSA`, no `CFMITNIPSA.SN`).
2. `name` es el nombre del fondo según el catálogo: `FM IT NOW S&P IPSA` o
   `FI Independencia Rentas Inmobiliarias`.
3. `source` identifica la fuente realmente usada: `ledgifi:9019` o `aindependencia:bolsa`.
4. `updated` es la **fecha del último punto**, no la fecha de ejecución.
5. `data` ordenado ascendente por `date`, sin fechas duplicadas, sin huecos rellenados.
6. `close` es numérico (no string), con hasta 4 decimales, redondeo half-up.
7. `date` en ISO `YYYY-MM-DD`, sin hora ni zona.
8. Serialización determinista: UTF-8, `indent=2`, newline final, orden de claves fijo
   (`ticker`, `name`, `currency`, `source`, `updated`, `data`). Dos ejecuciones con los mismos datos
   producen archivos **idénticos byte a byte** (hash SHA-256 igual).
9. Escritura atómica: archivo temporal en el mismo directorio + `os.replace`.
10. `currency` es siempre `CLP` para ambos fondos (no se lee de la fuente).

### 5.2 Archivo de backfill derivado: `docs/quotes/<TICKER>.backfill.json`

Mismo esquema, con `source` = `ledgifi:9019#indice` y `updated` = fecha del último punto derivado.
Solo existe si se pidió `--backfill N`. **Nunca** se mezcla con el archivo oficial: PP consume solo
`<TICKER>.json`.

`--backfill` aplica solo a fondos cuya fuente exponga serie de índice (hoy únicamente `CFMITNIPSA`).
Para `CFINRENTAS` es no-op con advertencia `[SIN CAMBIOS] CFINRENTAS backfill=no_disponible` y no
crea archivo; no altera el código de salida.

`--backfill N` con `1 ≤ N ≤ 155`; N cuenta los puntos de índice estrictamente anteriores a la fecha
del último punto oficial, tomados desde el final de la serie. El archivo se **regenera completo** en
cada corrida (no es append-only): dos corridas con los mismos datos producen bytes
idénticos. Un `N` fuera de rango es error de configuración, código `1`.
Si `N` excede la cantidad de puntos de índice estrictamente anteriores a la fecha del último punto
oficial, es error de configuración, código `1` (no se recorta a los disponibles).

### 5.3 Consumo en Portfolio Performance

Proveedor **JSON** (nativo, sin plugins), por instrumento:

- URL: `https://ginkelte.github.io/fund-quotes/quotes/{TICKER}.json`
- *Path to Date*: `$.data[*].date`
- *Path to Close*: `$.data[*].close`

El README debe además indicar que el sitio se publica desde la rama `main`, carpeta `/docs`, y cómo
verificar que la actualización ocurrió (ver `AC-09`).

## 6. Requisitos

### Adquisición y normalización

- **REQ-ADP-001** — Obtener y parsear la cuota de CFMITNIPSA desde LedgiFi (vía proxy), devolviendo
  `(fecha, valor)` de la serie `UNICA` o un error tipado. Timeout 30 s, máximo 2 MB de respuesta.
- **REQ-ADP-002** — Obtener y parsear la cuota de CFINRENTAS desde la serie `BOLSA` del sitio del
  administrador, con la fecha derivada en UTC según §4.2.
- **REQ-ADP-003** — Normalizar todo valor: quitar `$` y espacios, eliminar puntos de miles, cambiar
  coma decimal por punto, exigir `0 < close < 10000000` y redondear a 4 decimales. Un formato
  ambiguo (por ejemplo `1,234.56`) se rechaza, no se adivina.
- **REQ-ADP-004** — Backfill derivado opcional (`--backfill N`): `close(d) = close_conocido ×
  índice(d) / índice(último)`, redondeado a 4 decimales, escrito solo en `<TICKER>.backfill.json`.
  La semántica de `N`, el modo de escritura y el no-op para `CFINRENTAS` se norman en §5.2.

### Almacenamiento

- **REQ-STO-001** — Merge append-only: se conservan todos los puntos previos y se agregan los nuevos;
  sin duplicados de fecha; orden ascendente.
- **REQ-STO-002** — Idempotencia: si el punto de la fuente ya está guardado con el mismo valor, el
  archivo no se reescribe (mismo hash) y el proceso termina con código 0.
- **REQ-STO-003** — Escritura no destructiva: si el archivo existente no es JSON válido o no cumple
  el contrato, se aborta sin modificarlo. Nunca se trunca ni se vacía un feed.
- **REQ-STO-004** — Cumplir el contrato de §5.1 en cada escritura (claves, orden, formato, newline).

### Guarda de calidad

- **REQ-GRD-001** — Rechazar un punto cuyo `close` difiera más de **5,00%** del último punto guardado
  con fecha anterior, reportarlo como anomalía y no escribirlo. `--force-anomaly` lo acepta y deja
  registro del forzado en stdout. Sin punto previo, la guarda no aplica.

### Publicación

- **REQ-PUB-001** — Publicar `docs/quotes/<TICKER>.json` por cada fondo solicitado que haya quedado
  al día, sin tocar los demás archivos.
- **REQ-PUB-002** — Generar `docs/index.html` autocontenido (sin JS ni assets externos) con, por
  fondo: último cierre, fecha, fuente y días hábiles transcurridos desde el último punto; alerta
  visual si supera 3 días hábiles (L-V, sin feriados en v1). Días hábiles = días L-V en el intervalo
  `(último_punto, hoy]`; alerta si > 3. `docs/index.html` no contiene fecha ni hora de generación:
  dos corridas con los mismos feeds **y la misma fecha `--today`** producen el mismo HTML byte a byte.

### Operación

- **REQ-CLI-001** — CLI `python -m fund_quotes` con `--out`, `--status-page`, `--fondo`,
  `--force-anomaly`, `--backfill N`, `--dry-run`, `--today YYYY-MM-DD`, y códigos de salida de §8.
- **REQ-CLI-002** — Reportar en stdout, por fondo, la fuente usada y su resultado; los fallos van a
  stderr con motivo accionable en español de Chile.
- **REQ-CLI-003** — Reloj inyectable (`--today`, por defecto hoy en `America/Santiago`) para que la
  página de estado y las validaciones de fecha sean deterministas en tests.
- **REQ-CI-001** — Workflow diario de GitHub Actions (lunes a viernes, cron `30 23 * * 1-5`, es decir
  20:30 en Chile en horario de verano), `workflow_dispatch` manual, `permissions: contents: write`,
  commit solo si hay diff, y ejecución de los tests antes de publicar. El workflow commitea y publica
  los fondos exitosos **antes** de propagar el código de salida; después falla el job si el código es
  ≠ 0. El commit nunca se omite por un fondo caído.

### No funcionales y seguridad

- **REQ-NF-001** — Python 3.11, solo stdlib en producción; `pytest` únicamente como dev-dependency.
  Verificación manual en CI: `python3.11 -m pytest -q` y
  `grep -rhoE '^(from|import) [a-zA-Z0-9_.]+' fund_quotes | sort -u`
  (todos los módulos importados deben ser de la stdlib).
- **REQ-NF-002** — La suite corre sin red, contra fixtures guardados en `tests/fixtures/`.
- **REQ-NF-003** — Documentación, mensajes de error y página de estado en español de Chile.
- **REQ-SEC-001** — Sin secretos, credenciales, captcha-solving ni servicios pagos; solo URLs públicas.
  Verificación manual en CI: `grep -rniE 'token|secret|password|api[_-]?key|captcha' fund_quotes docs .github`
  sin coincidencias.
- **REQ-SEC-002** — Sin datos personales en el repo público: nada de RUT, montos de cartera ni número
  de cuotas. Los RUN de los fondos son públicos y se pueden citar.
  Verificación manual en CI: `grep -rniE '\bRUT\b|[0-9]{1,2}\.[0-9]{3}\.[0-9]{3}-[0-9kK]|cartera|cuotas' docs fund_quotes`
  sin coincidencias.
- **REQ-SEC-003** — Allowlist de dominios (`ledgifi.com`, `r.jina.ai`, `aindependencia.cl`), sin
  seguir redirecciones fuera de ella, tickers validados con `^[A-Z0-9]{1,15}$`, sin `eval`.
  Se cubre con unit tests de `fetch.py`: (a) host fuera de la allowlist → error, sin emitir la
  petición; (b) redirección hacia otro dominio → error.

## 7. Arquitectura propuesta

```
fund-quotes/
├── fund_quotes/
│   ├── __main__.py          # entrada: python -m fund_quotes
│   ├── cli.py               # argumentos, orquestación, exit codes, resumen final
│   ├── catalog.py           # registro estático de los 2 fondos (ticker, nombre, run, fuente, URL)
│   ├── fetch.py             # HTTP con timeout, tope de tamaño, allowlist y reintentos
│   ├── quote.py             # Quote(fecha, close) + normalización numérica (REQ-ADP-003)
│   ├── store.py             # lectura, merge append-only, serialización determinista, escritura atómica
│   ├── guards.py            # anomalía >5%, fechas implausibles, feed corrupto
│   ├── status_page.py       # docs/index.html (autocontenido)
│   └── sources/
│       ├── ledgifi.py       # adaptador A (+ índice para backfill)
│       └── aindependencia.py # adaptador B (serie BOLSA)
├── docs/
│   ├── index.html           # generado
│   └── quotes/<TICKER>.json # generado
├── specs/fund-quotes.spec.md
├── specs/fund-quotes.feature
├── tests/fixtures/          # HTML de muestra, sin red
└── .github/workflows/daily.yml
```

| Módulo | Responsabilidad | No hace |
|---|---|---|
| `cli.py` | Parsear flags, iterar fondos, agregar resultados, decidir exit code | Parsear HTML ni escribir archivos |
| `fetch.py` | Una petición por fuente y ejecución; reintentos; validar host, tamaño y status | Interpretar contenido |
| `sources/*` | Devolver `Quote` o `SourceError` con motivo accionable | Escribir en disco |
| `store.py` | Contrato de archivo, merge, hash estable, `os.replace` | Decidir si un valor es plausible |
| `guards.py` | Reglas de rechazo (anomalía, fecha futura, feed ilegible) | Publicar ni reintentar |
| `status_page.py` | Render de estado y alerta de días hábiles | Consultar la red |

Flujo por fondo: `fetch → parse → Quote → guarda → merge append-only → escritura atómica → resultado`.
Un fondo que falla no interrumpe a los demás: cada uno produce un resultado independiente
(`ok`, `sin_cambios`, `anomalia`, `falla`) y el CLI agrega esos resultados en el código de salida.

Contrato del CLI:

```
python -m fund_quotes [--out docs/quotes] [--status-page docs/index.html]
                      [--fondo TICKER ...] [--force-anomaly] [--backfill N]
                      [--dry-run] [--today YYYY-MM-DD]
```

`--dry-run` calcula todo y reporta, sin escribir archivos. `--today` existe solo para determinismo
de tests y de la página de estado; por defecto es la fecha actual en `America/Santiago`.

## 8. Comportamiento ante errores y casos borde

Códigos de salida (precedencia: 1 > 3 > 2 > 0):

| Código | Significado | Efecto sobre los archivos |
|---|---|---|
| `0` | Todos los fondos solicitados quedaron al día, o ya estaban al día | Sin cambios o con los puntos nuevos |
| `2` | Éxito parcial: al menos un fondo publicado y al menos uno fallido | Solo se escriben los fondos exitosos |
| `3` | Punto rechazado por la guarda (anomalía >5% o fecha implausible) | El feed afectado queda intacto |
| `1` | Error de configuración, feed existente ilegible, o todos los fondos fallaron | Ningún archivo se modifica |

Reglas transversales:

- Un punto solo se escribe si la fuente entregó **fecha y valor**. Nunca se usa la fecha de ejecución
  como sustituto de la fecha publicada.
- Nunca se trunca, vacía ni reordena un feed existente; la escritura es atómica y el archivo prevalece
  ante cualquier error.
- Reintentos: 2 (3 intentos en total), backoff de 5 s y 15 s, timeout 30 s, tope de 2 MB por respuesta.
- Formato de salida por fondo (una línea, español de Chile):
  `[OK] CFMITNIPSA fecha=2026-10-15 close=5054.2279 fuente=ledgifi:9019`,
  `[SIN CAMBIOS] ...`, `[ANOMALIA] CFINRENTAS variacion=+10,32% umbral=5,00% fecha=2026-10-15`,
  `[FALLA] CFMITNIPSA fuente=ledgifi:9019 motivo=<accionable>`.
- En GitHub Actions el resumen se agrega a `$GITHUB_STEP_SUMMARY`; los fallos no se silencian con
  `continue-on-error`.
- El workflow commitea y publica los fondos exitosos **antes** de propagar el código de salida;
  después falla el job si el código es ≠ 0. El commit nunca se omite por un fondo caído.

| ID | Caso borde | Comportamiento |
|---|---|---|
| EC-001 | La fuente publica el mismo día con un valor distinto al ya guardado | Se conserva el punto existente (append-only, sin reescribir historia), se advierte en stdout y el código de salida no cambia |
| EC-002 | Fecha de fuente posterior a hoy + 1 día | Se rechaza el punto como fecha implausible (posible error de zona horaria), código `3` |
| EC-003 | Fecha de fuente anterior al último punto guardado | No-op informativo, código `0` |
| EC-004 | No existe feed previo | Se crea con el punto de la fuente; la guarda de anomalía no aplica por falta de referencia |
| EC-005 | Respuesta con "Vercel Security Checkpoint", status 429, o cuerpo menor a 10 KB | Se trata como bloqueo: reintenta y luego falla ruidosamente |
| EC-006 | Valor con notación científica, sin decimales, o formato ambiguo (`1,234.56`) | Se rechaza por formato (`REQ-ADP-003`), no se adivina |
| EC-007 | Cada adaptador entrega exactamente un punto por corrida | El escenario de varios días nuevos no aplica en v1 (queda fuera de alcance) |
| EC-008 | Falla de escritura (permisos, disco lleno) | El archivo original queda intacto; código `1` |

## 9. Seguridad y límites

- **Sin secretos**: no hay tokens, credenciales ni variables sensibles. El workflow usa el
  `GITHUB_TOKEN` efímero con `permissions: contents: write` y nada más.
- **Sin captcha-solving**: si una fuente presenta un challenge, se usa el proxy documentado o se falla.
  No se intenta evadir el mecanismo del sitio.
- **Sin datos personales**: el repo es público. No se publican RUT, montos, número de cuotas ni
  ninguna cifra de la cartera. Solo se citan datos públicos de los fondos (RUN, nombre, tipo CMF).
- **Superficie de red acotada**: allowlist de hosts, HTTPS obligatorio, sin seguir redirecciones a
  otros dominios, tope de 2 MB, timeout 30 s, una petición por fuente y ejecución.
- **Sin ejecución de código remoto**: el JS de la Fuente B se extrae como texto y se pasa por
  `json.loads`; nunca por `eval`/`exec`.
- **Sin path traversal**: los tickers provienen del catálogo (allowlist) y se validan con
  `^[A-Z0-9]{1,15}$`; las rutas de escritura se resuelven bajo el repo y se rechazan las que salgan.
- **Privacidad del proxy**: `r.jina.ai` solo recibe la URL pública del fondo; no se le envían headers
  del usuario ni cookies.
- **Límite de alcance operativo**: el pipeline no corrige historia pasada, no rellena huecos y no
  interpreta series distintas de las documentadas en §4.

## 10. Criterios de aceptación

Los criterios son normativos; `specs/fund-quotes.feature` es su versión ejecutable en Gherkin
(`# language: es`). Cada criterio se numera y se traza a los requisitos de §6.

**AC-01 — Se publica la fecha real de la fuente, no la de ejecución**
- Dado un feed de `CFMITNIPSA` cuyo último punto es 2026-10-14 con cierre 5054.0853
- Y la Fuente A publica `$5.054,2279` al `15 de octubre de 2026`
- Cuando el pipeline corre con `--fondo CFMITNIPSA` y fecha simulada 2026-10-19
- Entonces el feed gana un punto con fecha 2026-10-15 y cierre 5054.2279
- Y el campo `updated` queda en 2026-10-15
- Y para `CFINRENTAS` la fecha del punto se deriva del epoch en UTC
  (`1792022400000` → 2026-10-15), no en hora de Chile

**AC-02 — Idempotencia: dos corridas el mismo día no modifican el feed**
- Dado un feed de `CFMITNIPSA` ya actualizado al 2026-10-15
- Cuando el pipeline corre dos veces con `--fondo CFMITNIPSA` y la misma fecha simulada
- Entonces la segunda corrida termina con código 0
- Y el hash SHA-256 del archivo es idéntico antes y después
- Y no hay fechas duplicadas

**AC-03 — Append-only: se conserva toda la historia previa**
- Dado un feed de `CFINRENTAS` con 100 puntos y último punto 2026-10-14
- Cuando el pipeline publica el punto del 2026-10-15
- Entonces el feed contiene 101 puntos
- Y los primeros 100 puntos son idénticos a los previos y en el mismo orden
- Y el último punto es 2026-10-15 con cierre 2181.18

**AC-04 — Una fuente sin la cuota esperada falla sin inventar datos**
- Dado un HTML de la Fuente A sin la fila de la serie `UNICA` con `Valor cuota`
- Y un feed de `CFMITNIPSA` con 2 puntos
- Cuando el pipeline corre con `--fondo CFMITNIPSA`
- Entonces termina con código `1`
- Y el error indica que no se encontró la cuota de `CFMITNIPSA`
- Y el feed conserva sus 2 puntos sin cambios
- Y no se agrega ningún punto con la fecha de ejecución

**AC-05 — Si una fuente cae, se usa la disponible y se reporta el fallo**
- Dado que la Fuente A responde 429 con "Vercel Security Checkpoint" en los tres intentos
- Y la Fuente B entrega la serie `BOLSA` hasta 2026-10-15
- Cuando el pipeline corre para ambos fondos
- Entonces `CFINRENTAS.json` gana el punto 2026-10-15
- Y `CFMITNIPSA.json` no cambia
- Y stdout reporta `CFMITNIPSA` como falla con su fuente y `CFINRENTAS` como publicada
- Y el proceso termina con código 2

**AC-06 — Un salto mayor a 5% se rechaza salvo override explícito**
- Dado un feed de `CFINRENTAS` con último punto 2026-10-14 y cierre 2175.45
- Y la fuente publica el 2026-10-15 un cierre de 2400.00 (+10,32%)
- Cuando el pipeline corre sin flags
- Entonces el punto se rechaza, el feed queda intacto y el proceso termina con código 3
- Y stdout reporta la anomalía con su variación y el umbral
- Y cuando el pipeline corre con `--force-anomaly`
- Entonces el punto se escribe, se registra el forzado y el código es 0

**AC-07 — Los tests corren en CI sin red**
- Dado un entorno de CI sin acceso a red
- Cuando se ejecuta `python -m pytest -q`
- Entonces todos los tests pasan
- Y ninguna prueba abre conexiones HTTP ni resuelve DNS (todo el parseo usa `tests/fixtures/`)

**AC-08 — Página de estado con último punto, fuente y alerta por antigüedad**
- Dado el feed de cada fondo con su último punto publicado
- Cuando se genera `docs/index.html` con fecha simulada 2026-10-19
- Entonces la página muestra por fondo el último cierre, la fecha, la fuente y los días hábiles
  transcurridos
- Y `CFMITNIPSA` con último punto 2026-10-15 aparece al día (2 días hábiles, sin alerta)
- Y con último punto 2026-10-08 aparece en alerta (7 días hábiles, supera el umbral de 3)
- Y los días hábiles se cuentan como días L-V en el intervalo `(último_punto, hoy]`, con alerta si > 3
- Y `docs/index.html` no incluye fecha ni hora de generación, por lo que dos corridas con los mismos
  feeds **y la misma fecha simulada** producen el mismo HTML byte a byte

**AC-09 — El README documenta la configuración en Portfolio Performance**
- Dado el `README.md` del repositorio
- Cuando se lee
- Entonces indica, para `CFMITNIPSA` y para `CFINRENTAS`, el proveedor "JSON" y la URL
  `https://ginkelte.github.io/fund-quotes/quotes/{TICKER}.json`
- Y los JSONPath `$.data[*].date` y `$.data[*].close`
- Y el instrumento en PP debe tener ticker exactamente `CFMITNIPSA`/`CFINRENTAS` (sin `.SN`),
  porque el macro `{TICKER}` se sustituye literalmente en la URL
- Y los pasos para verificar que PP actualizó las cotizaciones

**AC-10 — Parseo correcto del formato numérico y de fecha chileno**
- Dado un HTML de la Fuente A con `Valor cuota` y fecha de actualización en español
- Cuando el adaptador normaliza la cuota
- Entonces `$5.054,2279` con `15 de octubre de 2026` produce 5054.2279 y 2026-10-15
- Y `$1.234,5` con `1 de septiembre de 2026` produce 1234.5 y 2026-09-01
- Y un formato ambiguo como `1,234.56` se rechaza con error de formato

**AC-11 — El backfill derivado no contamina el feed oficial**
- Dado un feed oficial de `CFMITNIPSA` con 1 punto al 2026-10-15
- Y la página de la Fuente A con 156 puntos de índice, último `173.8262101046597` al 2026-10-15
- Cuando el pipeline corre con `--backfill 30`
- Entonces `CFMITNIPSA.json` sigue con 1 punto
- Y `CFMITNIPSA.backfill.json` contiene 30 puntos derivados anteriores al 2026-10-15
- Y cada cierre equivale a `5054.2279 × índice(d) / 173.8262101046597` redondeado a 4 decimales
- Y el `source` del archivo derivado contiene `indice`

**AC-12 — Un feed existente corrupto no se sobrescribe**
- Dado un `docs/quotes/CFINRENTAS.json` con JSON inválido
- Cuando el pipeline corre
- Entonces termina con código distinto de 0
- Y el error indica que el feed existente no se pudo leer
- Y el archivo conserva su contenido original byte a byte

**AC-13 — Contrato de serialización determinista**
- Dado el mismo conjunto de datos procesado en dos corridas independientes
- Cuando se serializa `docs/quotes/<TICKER>.json`
- Entonces las claves aparecen en el orden exacto `ticker`, `name`, `currency`, `source`, `updated`, `data`
- Y el archivo usa `indent=2`, UTF-8 sin BOM y termina con un `\n` final
- Y el SHA-256 de ambos archivos es idéntico

**AC-14 — `--dry-run` no escribe archivos**
- Dado un feed de cada fondo ya al día y una `docs/index.html` existente
- Cuando el pipeline corre con `--dry-run`
- Entonces el hash SHA-256 de `docs/quotes/*.json` y de `docs/index.html` es idéntico antes y después
- Y el proceso termina con código `0`

Trazabilidad con los criterios de referencia del encargo:

| AC | Criterio de referencia | Requisitos |
|---|---|---|
| AC-01 | R1 — fecha real publicada | REQ-ADP-001, REQ-ADP-002, REQ-CLI-003 |
| AC-02 | R2 — idempotencia | REQ-STO-002 |
| AC-03 | R3 — append-only | REQ-STO-001 |
| AC-04 | R4 — falla ruidosa sin inventar | REQ-ADP-001, REQ-STO-003, REQ-CLI-001 |
| AC-05 | R5 — una fuente disponible, otra caída | REQ-CLI-002, REQ-PUB-001 |
| AC-06 | R6 — anomalía >5% con flag | REQ-GRD-001 |
| AC-07 | R7 — tests sin red | REQ-NF-002, REQ-CI-001 |
| AC-08 | R8 — página de estado y alerta | REQ-PUB-002 |
| AC-09 | R9 — README con pasos para PP | REQ-NF-003 |
| AC-10 | Derivado de §4.1 y §4.2 (formato de fuentes) | REQ-ADP-003 |
| AC-11 | Derivado de §4.1 y §5.2 (backfill derivado) | REQ-ADP-004 |
| AC-12 | Derivado de §8 (protección del feed existente) | REQ-STO-003 |
| AC-01b | §4.2 (serie BOLSA, fecha en UTC) | REQ-ADP-002 |
| AC-10b | §6 (formato ambiguo rechazado) | REQ-ADP-003 |
| EC-001 | §8 (mismo día con otro valor) | REQ-STO-001 |
| EC-002 | §8 (fecha implausible) | REQ-GRD-001 |
| AC-13 | §5.1 reglas 7-8 (serialización determinista) | REQ-STO-004 |
| AC-14 | §7 (`--dry-run`) | REQ-CLI-001, REQ-PUB-001 |
| Unit tests de `fetch.py` | §9 (allowlist y redirecciones) | REQ-SEC-003 |

El archivo `.feature` incluye, además, dos escenarios marcados `@borde` (mismo día con otro valor
publicado, y fecha implausible) que no agregan criterios de aceptación nuevos: verifican reglas ya
normadas en §8.

**Verificación manual en CI (requisitos sin AC ejecutable)**

| Requisito | Comando exacto | Criterio |
|---|---|---|
| REQ-NF-001 | `python3.11 -m pytest -q` y `grep -rhoE '^(from|import) [a-zA-Z0-9_.]+' fund_quotes \| sort -u` | Todos los módulos importados pertenecen a la stdlib |
| REQ-SEC-001 | `grep -rniE 'token|secret|password|api[_-]?key|captcha' fund_quotes docs .github` | Sin coincidencias |
| REQ-SEC-002 | `grep -rniE '\bRUT\b|[0-9]{1,2}\.[0-9]{3}\.[0-9]{3}-[0-9kK]|cartera|cuotas' docs fund_quotes` | Sin coincidencias |

La allowlist de `REQ-SEC-003` se verifica con unit tests de `fetch.py`: host fuera de la allowlist →
error sin petición, y redirección hacia otro dominio → error.

## 11. Fuera de alcance explícito

- **Otras fuentes o APIs**: no se raspa la CMF, no se usan APIs de pago, no se agregan fondos,
  monedas ni instrumentos distintos de los dos de §1.
- **Corrección de historia pasada**: no se reescriben puntos ya publicados, no se interpolan huecos
  ni se "arreglan" valores retroactivamente. La única excepción es el backfill derivado, que vive en
  un archivo aparte.
- **Historia más profunda que la disponible**: la Fuente A entrega 156 puntos de índice desde
  2016-01-01; el pipeline no inventa historia anterior.
- **Cálculos de cartera**: rentabilidad, TIR, comparación con benchmark, valorización de posiciones
  y cualquier dato personal quedan fuera; eso lo hace PP.
- **Plugin o fork de Portfolio Performance**: se usa el proveedor JSON nativo, sin desarrollo en Java.
- **Interfaz interactiva**: no hay web app, ni formularios, ni base de datos; el sitio es estático.
- **Notificaciones**: no hay correo, Discord ni alertas push. La señal es el código de salida del
  workflow y la página de estado.
- **Feriados chilenos**: la alerta de §10 cuenta días L-V sin feriados en v1 (ver Q1).
- **Captcha-solving y automatización de navegador**: si el proxy deja de servir, el pipeline falla;
  no se implementa un navegador headless para evadir el challenge.

## 12. Preguntas abiertas

| ID | Pregunta | Propuesta MVP (supuesto aplicado) | Impacto si se decide distinto |
|---|---|---|---|
| Q1 | ¿La alerta de 3 días debe descontar feriados chilenos? | Contar solo días L-V, sin feriados. Un feriado largo puede generar una alerta falsa | Requiere una tabla estática de feriados (sin API) y un test adicional |
| Q2 | ¿La cuota del día ya está publicada a las 23:30 UTC, cuando corre el cron? | Asumir que sí; si aún no está, el punto entra en la corrida siguiente con su fecha real, sin pérdida | Un segundo cron (p. ej. 03:00 UTC) o un horario más tardío |
| Q3 | ¿Se acepta `r.jina.ai` como dependencia de disponibilidad de la Fuente A? | Sí, con reintentos y detección de checkpoint; no hay fuente oficial alternativa verificada | Sin proxy no hay Fuente A: habría que buscar otra fuente y revalidar el parseo |
| Q4 | Si la fuente corrige el mismo día con otro valor (ver el caso borde correspondiente en §8), ¿basta con conservar el primero? | Sí: se conserva el punto original y se advierte; no se reescribe historia | Se necesitaría un flag `--replace-last` con registro de auditoría |
| Q5 | ¿Los 156 puntos de índice (desde 2016-01-01) alcanzan para el backfill que se quiere importar en PP? | Sí; es toda la granularidad que publica la fuente | Habría que evaluar otra fuente histórica, hoy no verificada |

