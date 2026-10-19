# language: es
#
# Fuente normativa: specs/fund-quotes.spec.md (§10 Criterios de aceptación, §8 Casos borde).
# Los pasos describen comportamiento observable del CLI y del feed publicado; no imponen
# nombres de funciones ni estructura interna.
# Convención de nombres: "AC-NN" traza al criterio de aceptación; "EC-NNN" traza al caso borde.

Característica: Feed de cotizaciones diarias de dos fondos chilenos
  Como mantenedor del feed publicado en GitHub Pages
  Quiero acumular a diario la cuota publicada de cada fondo en un archivo JSON estático
  Para que Portfolio Performance actualice las cotizaciones sin depender de Yahoo Finance

  Antecedentes:
    Dado un repositorio con el pipeline instalado y el catálogo de los dos fondos
    Y los fixtures "tests/fixtures/ledgifi_9019.html" y "tests/fixtures/aindependencia_fondos.html" guardados

  # ════════════════════════════════════════════════════════════
  # ADQUISICIÓN Y NORMALIZACIÓN — REQ-ADP-*
  # ════════════════════════════════════════════════════════════

  # ── REQ-ADP-001: La Fuente A entrega la cuota con su fecha real ──

  Escenario: AC-01 la cuota se publica con la fecha de la fuente y no con la de ejecución
    Dado un feed de CFMITNIPSA con 2 puntos y último punto 2026-10-14 con cierre 5054.0853
    Y la Fuente A publica "Valor cuota" $5.054,2279 al "15 de octubre de 2026"
    Cuando ejecuto el pipeline con "--fondo CFMITNIPSA" y la fecha simulada 2026-10-19
    Entonces docs/quotes/CFMITNIPSA.json agrega el punto 2026-10-15 con cierre 5054.2279
    Y el campo updated del feed es 2026-10-15
    Y no existe ningún punto con fecha 2026-10-19
    Y el proceso termina con código 0

  # ── REQ-ADP-002: La Fuente B entrega la serie BOLSA con fecha en UTC ──

  Escenario: AC-01b la cuota de CFINRENTAS se toma de la serie BOLSA y su fecha es la del epoch en UTC
    Dado que el fixture de la Fuente B contiene la serie "BOLSA" con el punto [1792022400000, 2181.18]
    Y contiene además la serie "Valor Libro" con valores cercanos a 238947
    Cuando ejecuto el pipeline para CFINRENTAS con la fecha simulada 2026-10-19
    Entonces docs/quotes/CFINRENTAS.json agrega el punto 2026-10-15 con cierre 2181.18
    Y el cierre publicado no corresponde a la serie "Valor Libro"

  # ── REQ-ADP-003: Normalización del formato numérico y de fecha chileno ──

  Esquema del escenario: AC-10 los valores y fechas en formato chileno se normalizan
    Dado un HTML de la Fuente A con "Valor cuota" igual a "<texto>" y fecha de actualización "<fecha>"
    Cuando el adaptador de LedgiFi normaliza la cuota
    Entonces obtiene el cierre <cierre> y la fecha <iso>
    Ejemplos:
      | texto       | fecha                   | cierre    | iso        |
      | $5.054,2279 | 15 de octubre de 2026   | 5054.2279 | 2026-10-15 |
      | $1.234,5    | 1 de septiembre de 2026 | 1234.5    | 2026-09-01 |
      | $987,6543   | 31 de diciembre de 2025 | 987.6543  | 2025-12-31 |

  Escenario: AC-10b un formato numérico ambiguo se rechaza en vez de adivinar
    Dado un HTML de la Fuente A con "Valor cuota" igual a "1,234.56"
    Cuando el adaptador de LedgiFi intenta normalizar la cuota
    Entonces falla con un error de formato
    Y no se escribe ningún punto en docs/quotes/CFMITNIPSA.json

  # ── REQ-ADP-004: El backfill derivado vive en su propio archivo ──

  Escenario: AC-11 el backfill derivado no contamina el feed oficial
    Dado un feed oficial de CFMITNIPSA con 1 punto al 2026-10-15 y cierre 5054.2279
    Y la Fuente A incluye 156 puntos de índice con último valor 173.8262101046597 al 2026-10-15
    Cuando ejecuto el pipeline con "--backfill 30"
    Entonces docs/quotes/CFMITNIPSA.json sigue teniendo 1 punto
    Y docs/quotes/CFMITNIPSA.backfill.json contiene 30 puntos anteriores al 2026-10-15
    Y cada cierre derivado es igual a 5054.2279 multiplicado por su índice y dividido por 173.8262101046597, con 4 decimales
    Y el campo source del archivo derivado contiene "indice"

  # ════════════════════════════════════════════════════════════
  # ALMACENAMIENTO APPEND-ONLY — REQ-STO-*
  # ════════════════════════════════════════════════════════════

  # ── REQ-STO-002: Idempotencia byte a byte ──

  Escenario: AC-02 dos ejecuciones el mismo día no modifican el feed
    Dado un feed de CFMITNIPSA ya actualizado al 2026-10-15
    Cuando ejecuto el pipeline dos veces con "--fondo CFMITNIPSA" y la fecha simulada 2026-10-19
    Entonces ambas ejecuciones terminan con código 0
    Y el hash SHA-256 del feed es el mismo antes y después de la segunda ejecución
    Y el feed contiene exactamente una entrada por fecha

  # ── REQ-STO-001: Se conserva toda la historia previa ──

  Escenario: AC-03 el feed conserva la historia previa al agregar el punto del día
    Dado un feed de CFINRENTAS con 100 puntos cuyo último punto es 2026-10-14 con cierre 2175.45
    Cuando ejecuto el pipeline para CFINRENTAS
    Entonces el feed contiene 101 puntos
    Y los primeros 100 puntos son idénticos a los previos y conservan su orden
    Y el último punto es 2026-10-15 con cierre 2181.18

  # ── REQ-STO-001: El mismo día con otro valor no reescribe la historia ──

  @borde
  Escenario: EC-001 un punto del mismo día con otro valor se conserva como estaba
    Dado un feed de CFMITNIPSA cuyo último punto es 2026-10-15 con cierre 5054.2279
    Y la Fuente A publica el 2026-10-15 un cierre de 5054.5000
    Cuando ejecuto el pipeline con "--fondo CFMITNIPSA" y la fecha simulada 2026-10-19
    Entonces el feed conserva el cierre 5054.2279 para el 2026-10-15
    Y la salida estándar advierte que el punto ya existía con otro valor
    Y el proceso termina con código 0

  # ── REQ-STO-003: Un feed ilegible nunca se sobrescribe ──

  Escenario: AC-12 un feed existente corrupto no se sobrescribe
    Dado un docs/quotes/CFINRENTAS.json con JSON inválido
    Cuando ejecuto el pipeline para CFINRENTAS
    Entonces el proceso termina con un código distinto de 0
    Y el mensaje de error indica que el feed existente no se pudo leer
    Y el archivo conserva su contenido original byte a byte

  # ════════════════════════════════════════════════════════════
  # GUARDA DE CALIDAD — REQ-GRD-*
  # ════════════════════════════════════════════════════════════

  # ── REQ-GRD-001: Anomalía sobre 5% con override explícito ──

  Esquema del escenario: AC-06 un salto mayor a 5% se rechaza salvo con --force-anomaly
    Dado un feed de CFINRENTAS cuyo último punto es 2026-10-14 con cierre 2175.45
    Y la Fuente B publica el 2026-10-15 un cierre de 2400.00
    Cuando ejecuto el pipeline <modo>
    Entonces el proceso termina con código <codigo>
    Y el feed <resultado>
    Y la salida estándar reporta una anomalía de +10,32% contra el umbral de 5,00%
    Ejemplos:
      | modo                | codigo | resultado                                |
      | sin flags           | 3      | conserva 1 punto                         |
      | con --force-anomaly | 0      | contiene 2 puntos y el último es 2400.00 |

  # ── REQ-GRD-001: Fechas implausibles ──

  @borde
  Escenario: EC-002 una fecha posterior a mañana se rechaza por implausible
    Dado un feed de CFINRENTAS con último punto 2026-10-14
    Y la Fuente B publica un punto con fecha 2026-10-25
    Cuando ejecuto el pipeline con la fecha simulada 2026-10-19
    Entonces el punto se rechaza con un error de fecha implausible
    Y el feed no se modifica

  # ════════════════════════════════════════════════════════════
  # PUBLICACIÓN Y ESTADO — REQ-PUB-*
  # ════════════════════════════════════════════════════════════

  # ── REQ-PUB-002: Página de estado con alerta por antigüedad ──

  Esquema del escenario: AC-08 la página de estado alerta cuando el último punto supera 3 días hábiles
    Dado un feed de CFMITNIPSA con último punto el <ultimo>
    Y un feed de CFINRENTAS con último punto el 2026-10-15
    Cuando genero la página de estado con la fecha simulada 2026-10-19
    Entonces docs/index.html muestra el último cierre, la fecha y la fuente de cada fondo
    Y el estado de CFMITNIPSA es <estado>
    Ejemplos:
      | ultimo     | estado                                        |
      | 2026-10-15 | al día, con 2 días hábiles y sin alerta        |
      | 2026-10-08 | en alerta, con 7 días hábiles sobre el umbral  |

  # ════════════════════════════════════════════════════════════
  # FALLAS Y REPORTE — REQ-CLI-*
  # ════════════════════════════════════════════════════════════

  # ── REQ-CLI-001: Falla ruidosa cuando la fuente no trae la cuota ──

  Escenario: AC-04 una fuente sin la cuota esperada falla sin inventar datos
    Dado un HTML de la Fuente A que no trae la fila de la serie UNICA con "Valor cuota"
    Y un feed de CFMITNIPSA con 2 puntos
    Cuando ejecuto el pipeline para CFMITNIPSA
    Entonces el proceso termina con código 1
    Y el mensaje de error indica que no se encontró la cuota de CFMITNIPSA
    Y el feed conserva sus 2 puntos sin cambios
    Y no se agrega ningún punto con la fecha de ejecución

  # ── REQ-CLI-002 / REQ-PUB-001: Una fuente caída no bloquea a la otra ──

  Escenario: AC-05 si una fuente falla se publica la otra y se reporta el fallo
    Dado que la Fuente A responde 429 con "Vercel Security Checkpoint" en los tres intentos
    Y la Fuente B entrega la serie BOLSA hasta el 2026-10-15
    Cuando ejecuto el pipeline para ambos fondos
    Entonces docs/quotes/CFINRENTAS.json agrega el punto 2026-10-15 con cierre 2181.18
    Y docs/quotes/CFMITNIPSA.json queda sin cambios
    Y la salida estándar reporta CFMITNIPSA como falla con su fuente y CFINRENTAS como publicada
    Y el proceso termina con código 2

  # ── REQ-NF-002 / REQ-CI-001: La suite corre sin red ──

  Escenario: AC-07 la suite de pruebas corre sin red con fixtures guardados
    Dado un entorno sin acceso a red
    Cuando ejecuto "python -m pytest -q" en la raíz del repositorio
    Entonces todos los tests pasan
    Y ninguna prueba abre conexiones HTTP ni resuelve nombres DNS

  # ════════════════════════════════════════════════════════════
  # DOCUMENTACIÓN — REQ-NF-003
  # ════════════════════════════════════════════════════════════

  # ── REQ-NF-003: Pasos exactos para configurar cada instrumento en PP ──

  Escenario: AC-09 el README documenta la configuración de cada instrumento en Portfolio Performance
    Dado el README.md del repositorio
    Cuando lo reviso para configurar los instrumentos CFMITNIPSA y CFINRENTAS
    Entonces indica el proveedor "JSON" y una URL con el patrón "https://ginkelte.github.io/fund-quotes/quotes/{TICKER}.json" para cada instrumento
    Y indica los JSONPath "$.data[*].date" y "$.data[*].close"
    Y describe cómo verificar que Portfolio Performance quedó actualizando
