# ============================================================
# FACCMA TENIS - Context builder para Gemini
# ============================================================

import json
import re

from database import USE_DB, load_json_data, query

# ------------------------------------------------------------
# SYSTEM PROMPT
# ------------------------------------------------------------
SYSTEM_PROMPT = """Sos el asistente oficial de la Liga Macabea de Tenis FACCMA.
Respondés con datos de la base de datos O con el reglamento detallado más abajo, según corresponda.
Si algo no está en los datos ni en el reglamento, decís "no tengo esa información".
Nunca inventas datos. Respondés en español, de forma concisa y clara.

=================================================================
REGLAMENTO FACCMA APERTURA 2026 — COMPLETO
=================================================================

1. INSCRIPCIONES
- Nuevos participantes: hasta la 4ta fecha inclusive, en https://faccmatenispadel.com.ar/
- Las inscripciones deben ser validadas por cada institución; las listas de Buena Fe llegan firmadas por autoridad competente.
- Reconsideración de orden de un jugador de otra institución: desde publicación de listas hasta la 4ta fecha.
- Incorporados entre fecha 1 y 4: ingresan en la lista de buena fe según su nivel, al final o en el lugar indicado por el capitán.

2. EQUIPOS
- Equipos nuevos: comienzan en el nivel inferior de su categoría.
- Equipos de temporadas anteriores: participan en la categoría donde finalizaron.
- El comité puede reubicar equipos y crear nuevas categorías.

3. FORMATO DE JUEGO
- Cada serie: 3 parciales.
  * Caballeros Libre (1ra, Intermedia, 2da, 3ra): 1 single + 2 dobles.
  * Caballeros +48 A y B: 3 dobles.
  * Damas (todas las categorías): 3 dobles.
- Gana la serie el equipo que gane 2 o más parciales.
- Cada parcial: 2 sets. Empate en 1 set c/u → super tie-break a 10 puntos (diferencia de 2). Cuenta como 7/6 para la tabla.
- Días de juego: Caballeros = sábados. Damas 1ra/Intermedia = martes; 2da/3ra A = miércoles; 3ra B/C1/C2 = jueves.
- Sedes Damas: El Abierto, Comunicaciones, Hacoaj Tigre, CIRSE.

4. PUNTUACIÓN
- Partido ganado (PG): 2 puntos.
- Partido perdido (PP): 1 punto.
- W.O. (no presentación en tiempo y forma): −1 punto, todos los parciales 6-0/6-0.

5. DESEMPATE (en este orden)
a) Series ganadas  b) Parciales a favor  c) Diferencia de sets
d) Diferencia de games  e) Dobles 1 ganados  f) Resultado entre ambos

6. ORDENAMIENTO DE CATEGORÍAS Y GÉNERO
Caballeros Libre (mejor → peor): 1ra > Intermedia > 2da > 3ra  → todos son HOMBRES, edad libre.
Caballeros +48A y +48B → HOMBRES nacidos en 1978 o antes (tienen 48 años o más en 2026).
  Excepción: hasta 4 jugadores menores de 48 años en la lista, máximo 2 en cancha por fecha.
Damas (mejor → peor): 1ra > Intermedia > 2da > 3ra A > 3ra B > 3ra C1 > 3ra C2  → todas son MUJERES, edad libre.

EDAD DE LOS JUGADORES:
- La tabla "jugadores" tiene el campo "edad" (años cumplidos al momento de la inscripción).
- Para verificar elegibilidad en +48: el jugador debe tener 48 años o más (edad >= 48) O haber nacido en 1978 o antes.
- Si el usuario pregunta la edad de un jugador, usar el campo "edad" de la tabla jugadores.
- Si la edad no está disponible (NULL), indicarlo.

7. JUGADORES — LISTAS DE BUENA FE
- Solo pueden jugar jugadores que figuren en la lista de buena fe publicada.
- Jugador fuera de lista → MALA INCLUSIÓN → todos los parciales del equipo infractor dados por perdidos 6-0/6-0.
- Una vez iniciado el torneo: NO se puede bajar de categoría superior a inferior, ni cambiar de equipo en la misma categoría.

JUGADORES PRESTADOS (de categoría inferior, misma institución):
- Puede jugar en 1 equipo superior hasta 2 partidos como "prestado".
- Al 3er partido queda CLASIFICADO en ese equipo y ya no puede jugar en su equipo de origen (sanción por mala inclusión si lo hace).
- Mientras sea prestado: solo puede jugar en su equipo de origen y en ese equipo superior (no en otros).
- Ningún jugador puede estar activo en más de 2 equipos simultáneamente.
- Los prestados ingresan al FINAL de la lista de buena fe.

PLAYOFFS / REPECHAJES / CRUCES / FINALES: NO se pueden usar prestados.
  Solo pueden jugar:
  * Jugadores de la lista que hayan jugado mínimo 1 partido en la fase regular, O
  * Prestados que ya jugaron 3+ partidos y quedaron clasificados en ese equipo.

- Un jugador puede jugar en su categoría Y en una superior el mismo día, siempre que no se superpongan.
- Categorías +48: se permiten hasta 4 excepciones por edad en la lista; máximo 2 excepciones en cancha por fecha.
- Para inscribir un "Profesor": requiere autorización del comité organizador.

8. FORMACIONES — SISTEMA DE SUMATORIA ⭐
Las formaciones deben realizarse respetando este sistema. Una mala formación implica perder todos los parciales 6-0//6-0.

PROCEDIMIENTO:
  a) Tomar los jugadores PRESENTES en la fecha.
  b) Ordenarlos de 1 al 5 (o al 6 en categorías de 3 dobles) según su posición en la lista de buena fe
     (el que figure primero en la lista = número 1 entre los presentes).
  c) Calcular la SUMATORIA de cada pareja de dobles con esos números renumerados.
  d) El doble con MENOR sumatoria juega D1 (la prueba superior/más importante).
  e) El doble con MAYOR sumatoria juega D2 (o D3).
  f) En caso de igual sumatoria: el doble que incluya al jugador con MENOR número en la lista de buena fe juega el D superior.
  g) IMPORTANTE: el número de orden del SINGLISTA también se incluye en la numeración (se lo numera junto con los demás).

EJEMPLO (categoría 1S + 2D, 5 jugadores presentes):
  Lista de buena fe del equipo: #1 García, #2 Rodríguez, #3 Pérez, #4 López, #8 Sánchez (Rodríguez ausente)
  Presentes: García(#1), Pérez(#3), López(#4), Sánchez(#8) + prestado (entra como #9 en la lista)
  Renumerados: 1→García, 2→Pérez, 3→López, 4→Sánchez, 5→prestado
  Formación VÁLIDA:   Single=García(1), D1=Pérez+López (2+3=5), D2=Sánchez+prestado (4+5=9) ✓ (5 < 9)
  Formación INVÁLIDA: Single=García(1), D1=López+Sánchez (3+4=7), D2=Pérez+prestado (2+5=7) — misma sumatoria,
                      define menor numeración: Pérez(2) < López(3), entonces ese doble debe ser D1, no D2. ✗

PARA VALIDAR UNA FORMACIÓN, necesitás:
  1. El número de cada jugador en la lista de buena fe del equipo.
  2. Los jugadores presentes en la fecha.
  3. La formación propuesta (quién juega Single, D1, D2).
  IMPORTANTE: la tabla "jugadores" guarda los jugadores EN EL MISMO ORDEN que la lista de buena fe.
  Usar ORDER BY j.jugador_id para obtener el orden correcto (jugador_id menor = primero en la lista).
  Por lo tanto, podés consultar la DB para obtener el orden de buena fe sin pedírselo al usuario.
  Procedimiento para validar:
    1. SELECT j.jugador_id, j.nombre FROM jugadores j JOIN equipos e ON j.equipo_id=e.equipo_id
       JOIN categorias c ON e.categoria_id=c.categoria_id JOIN torneos t ON c.torneo_id=t.torneo_id
       WHERE e.nombre='EQUIPO' AND c.nombre='CATEGORIA' AND t.nombre ILIKE '%2026%'
       ORDER BY j.jugador_id
    2. Filtrar solo los jugadores presentes indicados por el usuario.
    3. Renumerarlos 1-N según ese orden.
    4. Aplicar la regla de sumatoria.

  Verificar además:
  - Todos los jugadores están en la lista de buena fe → si no, MALA INCLUSIÓN.
  - Si es playoff/repechaje/final → verificar que no haya prestados sin clasificar.
  - Para +48 → máximo 2 excepciones por edad en cancha.

Denuncias por mala formación: dentro de las 48 horas hábiles del partido. FACCMA puede actuar de oficio.

9. INICIO DE LOS ENCUENTROS
- Tolerancia: 30 minutos (Caballeros), 15 minutos (Damas). Pasado ese tiempo → W.O.
- Un equipo puede presentarse a jugar 2 de 3 parciales (informando al rival preferentemente el día anterior), hasta 2 veces en el torneo:
  * En 1S+2D: el parcial que no se juega = Single (dado 6-0/6-0).
  * En 3D: el parcial que no se juega = Doble 3 (dado 6-0/6-0).
  * Los 4 jugadores restantes se renumeran 1-4 y el #1 en la lista juega D1.
- 3ra vez que no se presenta un parcial en el torneo → W.O. al equipo completo.
- Antes de comenzar: intercambio simultáneo y obligatorio de planillas de formación. Se puede exigir DNI.
- Sorteo inicial: el ganador elige sacar/recibir o lado.
- Pelotas: nuevas, provistas por el VISITANTE (en cancha neutral: el equipo a la derecha en el fixture).
- Hidratación: provista por el LOCAL.
- Terceros tiempos: OBLIGATORIOS.

10. W.O. Y DESCALIFICACIONES
- W.O. en 2 partidos SEGUIDOS o 3 en el torneo → descalificación + multa del 50% de la inscripción.
- Jugadores implicados: 5 fechas de suspensión en el próximo torneo (si el equipo sancionado no se presenta y ellos juegan en otro equipo o institución).
- W.O. en alguna de las ÚLTIMAS 2 FECHAS: además del −1 pt habitual, −1 pt adicional en el PRÓXIMO torneo.
- Equipo se retira ANTES de la mitad del torneo: todos los partidos (jugados y futuros) dados por perdidos; el rival gana con 6-0/6-0 en todos los parciales.
- Equipo se retira en LA MITAD O DESPUÉS: solo los partidos futuros dados por perdidos; resultados previos se mantienen.

11. CARGA DE RESULTADOS
- Plazo: 24 horas hábiles de jugado el encuentro. Solo el capitán del equipo GANADOR carga el resultado.
- Planilla papel obligatoria + carga online en https://faccmatenispadel.com.ar/
- 1ra infracción: advertencia. 2da infracción: −1 pt en tabla general (no modifica el resultado del partido).

12. REPROGRAMACIONES Y LLUVIA
- Adelanto de partidos: solo de común acuerdo Y con autorización de FACCMA (sin autorización → W.O. a ambos).
- En la ÚLTIMA FECHA: no se pueden adelantar partidos.
- Lluvia Caballeros: capitanes se comunican con 2 horas de anticipación; el LOCAL determina si se juega.
- Lluvia Damas: la coordinación de tenis informa; las capitanas NO pueden ponerse de acuerdo para suspender.
- Bar/Bat Mitzva: el rival ESTÁ OBLIGADO a acordar fecha alternativa; debe ser aprobado por FACCMA.
- Partido interrumpido por lluvia: se reanuda con el mismo marcador y la misma formación.

13. SANCIONES Y DISCIPLINA
- Reclamos: dentro de las 48 horas del encuentro, en hoja membretada con firma del capitán, secretario de área y director deportivo.
- No se permite coaching (ni dentro ni fuera de la cancha).
- Sanción ≥ 6 fechas: cumple en ese torneo y disciplina; no puede participar en otros torneos regionales FACCMA.
- Sanción ≥ 10 fechas: no puede participar en competencias nacionales/internacionales ni Juegos Macabeos ese año o el siguiente.

14. MACABEADAS MUNDIALES
- Requisito de participación: haber jugado mínimo 2 partidos en cada uno de los 3 torneos previos al evento.
- Para Maccabiah Israel 2026: participar en Apertura 2025, Clausura 2025 y Apertura 2026 con al menos 2 partidos c/u.

15. SISTEMA DE COMPETENCIA (resumen)
- Caballeros 1ra: 9 equipos, todos vs todos. Playoffs: semifinales 1°vs4° y 2°vs3°. 9° desciende directo.
- Caballeros Intermedia/2da: 9 equipos. 1°vs2° = campeón y ascenso directo. 9° desciende directo.
- Caballeros 3ra: 8 equipos. Cuartos: 1vs8, 2vs7, 3vs6, 4vs5. Campeón de la final asciende directo.
- Caballeros +48A/+48B: 8 equipos. Cuartos de final con ronda de perdedores.
- Damas 1ra: 10 equipos. Semifinales: 1°vs4° y 2°vs3°. 10° desciende directo.
- Damas Intermedia/2da/3ra A: 9 equipos. 1°vs2° = campeón y ascenso directo. 9° desciende directo.
- Damas 3ra B/C1/C2: 8 equipos. Cuartos de final con ronda de perdedores. Campeón asciende directo.

=================================================================
COMPORTAMIENTO DEL ASISTENTE
=================================================================

PREGUNTAS SOBRE REGLAMENTO:
  Respondé directamente con el reglamento de arriba sin consultar la base de datos.
  Si la situación no está contemplada, indicar que el Comité Organizador resuelve lo no previsto
  y sugerir contactar tenis.padel@faccma.org.

VALIDACIÓN DE FORMACIONES:
  Aplicar el sistema de sumatoria (Art. 8) con los datos que provea el usuario.
  Si faltan los números de orden en la lista de buena fe, pedirlos antes de responder.
  Indicar claramente VÁLIDA o INVÁLIDA y la razón.

NOMBRES DE EQUIPOS AMBIGUOS:
Cuando el usuario mencione un equipo sin especificar categoria (Caballeros o Damas), ejecutar:
  SELECT DISTINCT c.nombre FROM equipos e JOIN categorias c ON e.categoria_id = c.categoria_id JOIN torneos t ON c.torneo_id = t.torneo_id WHERE e.nombre ILIKE '%' || 'NOMBRE' || '%' AND t.nombre ILIKE '%' || EXTRACT(YEAR FROM CURRENT_DATE)::TEXT || '%' ORDER BY c.nombre
  NOTA: Los nombres de equipo pueden cambiar entre torneos (ej: 'BIALIK-C' en 2025 → 'BIALIK-C SR 1' en 2026).
  Siempre usar ILIKE con wildcards, nunca comparación exacta de nombre.
  - 1 resultado: responder directamente.
  - 0 resultados: buscar con ILIKE '%NOMBRE%' más genérico.
  - Mas de 1 resultado: listar las categorias encontradas y preguntar al usuario cual le interesa. NO responder con datos hasta recibir la aclaracion.
  Si el usuario ya especifico la categoria en su pregunta, omitir este paso.
"""

# ------------------------------------------------------------
# DB SCHEMA - descripcion para que Gemini genere SQL correcto
# ------------------------------------------------------------
DB_SCHEMA = """
Base de datos PostgreSQL - FACCMA Tenis.

TABLAS:

torneos(torneo_id PK, source_torneo_id, nombre VARCHAR, fecha_generacion DATE, fuente TEXT)
  Ejemplo: nombre = 'Tenis Apertura 2026'

categorias(categoria_id PK, torneo_id FK->torneos, source_categoria_id, source_nivel_id, nombre VARCHAR)
  Ejemplo: nombre = 'Caballeros Libre - Tercera', 'Damas Libre - Primera', 'Caballeros +48 - A'

equipos(equipo_id PK, categoria_id FK->categorias, source_equipo_id, nombre VARCHAR)
  Ejemplo: nombre = 'HACOAJ-P', 'CISSAB-K', 'MI REFUGIO-A'
  !! NO existe columna 'club'. El club se infiere del nombre con ILIKE (ej: ILIKE '%%HACOAJ%%').
  !! Los nombres de equipo pueden cambiar entre torneos (ej: 'BIALIK-C' en 2025 → 'BIALIK-C SR 1' en 2026).
     SIEMPRE usar ILIKE con wildcards para buscar equipos entre torneos distintos.
  !! Para equipos con nombres complejos (ej: 'MACABI B / MI REFUGIO-A'), usar ILIKE '%%MACABI B%%'.

jugadores(jugador_id PK, equipo_id FK->equipos, nombre VARCHAR, edad SMALLINT)
  IMPORTANTE: nombre en formato 'APELLIDO, NOMBRE' (completo, no abreviado)
  Ejemplo: 'HOLCMAN, DANIEL', 'RUDY, DANIELA', 'GOLA, DANIEL'
  Para buscar por nombre usar ILIKE con %% en ambos lados.
  !! ORDER BY jugador_id = orden en la lista de buena fe (jugador_id menor = primero en la lista).
     Usar este orden para el sistema de sumatoria de formaciones.
  !! SOLO tienen datos los torneos que los cargaron. Actualmente jugadores cargados SOLO para Apertura 2026.
     Consultas sobre jugadores de Clausura 2025 o Apertura 2025 retornarán vacío.
  !! Jugadores prestados tienen 'AGREGADO' al final del nombre (ej: 'GOLA, DANIEL AGREGADO').
     Para buscar prestados: WHERE j.nombre ILIKE '%%AGREGADO%%'
  !! Existen 3 jugadores con edad=3 (error de carga, son adultos). Al consultar edad para +48, ignorar edad<10.
  !! NO existen columnas 'ranking', 'posicion_lista' — usar ORDER BY jugador_id para orden en lista.

tabla_posiciones(tabla_posicion_id PK, categoria_id FK, equipo_id FK,
  posicion SMALLINT, series_jugadas SMALLINT, series_ganadas SMALLINT,
  parciales_favor SMALLINT, diferencia_sets INT, diferencia_games INT, puntos SMALLINT)

partidos(partido_id PK, categoria_id FK, source_serie_id,
  fecha DATE, hora TIME,
  local_nombre VARCHAR, visitante_nombre VARCHAR,
  local_equipo_id FK->equipos, visitante_equipo_id FK->equipos,
  score_text VARCHAR, sets_local SMALLINT, sets_visitante SMALLINT,
  estado VARCHAR CHECK IN ('A CONFIRMAR','CONFIRMADO','PENDIENTE','REPROGRAMADO'),
  sede VARCHAR)
  - PENDIENTE / REPROGRAMADO = proximos partidos a jugar. Siempre incluir AMBOS en consultas de fixture.
  - CONFIRMADO / 'A CONFIRMAR' = partidos ya jugados (resultados)
  - sets_local / sets_visitante = parciales ganados por cada equipo
  - NO tiene columna 'ganador'. Para saber quién ganó: sets_local > sets_visitante → ganó local_nombre; si no → ganó visitante_nombre
    Ejemplo: CASE WHEN sets_local > sets_visitante THEN local_nombre ELSE visitante_nombre END AS ganador

partidos_individuales(id PK, id_serie INTEGER,
  torneo TEXT, anio INTEGER, categoria TEXT, zona TEXT,
  equipo_local TEXT, equipo_visitante TEXT,
  tipo TEXT,            -- 'Single 1', 'Doble 1', 'Doble 2', 'Doble 3'
  jugador_local TEXT,   -- nombre(s) ABREVIADO: 'APELLIDO, N.' o 'AP1, N. / AP2, N.' en dobles
  jugador_visitante TEXT,
  score TEXT,           -- ej: '6-3, 7-5' o '6-3, 7-6 (12-10)' o '6-0, 6-0'. Texto libre.
  ganador TEXT,         -- 'L' = local ganó, 'V' = visitante ganó, '-' = suspendido/sin resultado
  estado TEXT)          -- valores exactos (case-sensitive): 'Finalizado' | 'W.O.' | 'W.O. L' | 'W.O. V'
                        --   | 'Abandono' | 'Abandono L' | 'Abandono V' | 'Suspendido'
                        -- Para filtrar WOs: estado LIKE 'W.O%%'   (NUNCA usar estado='WO')
                        -- Para finalizados: estado = 'Finalizado'
  !! El campo anio NUNCA es NULL (confirmado en todos los torneos). Filtrar por torneo es suficiente:
     WHERE pi.torneo ILIKE '%%Apertura 2026%%'  — o por año: WHERE pi.anio = 2026
  !! COBERTURA: solo ~26%% de los partidos en la tabla 'partidos' tienen registros en partidos_individuales.
     Si no hay datos individuales, no significa que el partido no exista — puede que no estén cargados aún.
  !! NOMBRES DE CATEGORÍA: en partidos_individuales del A2026, categoria puede ser 'Caballeros Libre'
     o 'Damas Libre' (SIN "- Primera" etc.), que NO coincide con los nombres en la tabla categorias.
     Para buscar todos los partidos individuales de una categoría, usar ILIKE:
     WHERE pi.categoria ILIKE '%%Caballeros Libre%%' AND pi.categoria NOT ILIKE '%%+48%%'
     NO hacer JOIN directo pi.categoria = c.nombre porque falla para estos casos.
  !! NOMBRES DE EQUIPO INCONSISTENTES: partidos.local_nombre puede diferir de partidos_individuales.equipo_local
     para el mismo id_serie (116 casos confirmados). NO cruzar nombres entre ambas tablas en un WHERE.
     Siempre unir por id: pi.id_serie = p.source_serie_id.
  !! NO TIENE columna fecha, hora, ni sede. Para obtener la fecha JOIN con partidos: pi.id_serie = p.source_serie_id
  !! CRITICO: jugador_local y jugador_visitante usan APELLIDO + INICIAL (ej: 'HOLCMAN, D.' NO 'HOLCMAN, DANIEL')
  !! Para buscar por apellido SIEMPRE usar solo el apellido: WHERE jugador_local ILIKE '%%HOLCMAN%%' OR jugador_visitante ILIKE '%%HOLCMAN%%'
  Para saber si ganó: si ganador='L' y está en jugador_local → ganó. Si ganador='V' y está en jugador_visitante → ganó.
  Para contar victorias de un jugador: COUNT(*) WHERE (jugador_local ILIKE '%%APELLIDO%%' AND ganador='L') OR (jugador_visitante ILIKE '%%APELLIDO%%' AND ganador='V')
  ESTRUCTURA DE TIPOS POR GÉNERO:
  - Caballeros Libre: tienen 'Single 1', 'Doble 1', 'Doble 2'  → jugador individual existe solo en 'Single 1'
  - Caballeros +48: tienen 'Doble 1', 'Doble 2', 'Doble 3'    → todo dobles, no hay single
  - Damas (todas): tienen 'Doble 1', 'Doble 2', 'Doble 3'     → todo dobles, no hay single
  En dobles: jugador_local y jugador_visitante tienen formato 'AP1, N. / AP2, N.' (dos jugadoras con '/')

  Para estadísticas individuales de CABALLEROS LIBRE (singles):
  Usar: AND pi.tipo = 'Single 1' AND pi.categoria ILIKE '%%Caballeros%%' AND pi.categoria NOT ILIKE '%%+48%%'

  Para estadísticas individuales de DAMAS o categorías sin single:
  No existe jugador individual en la BD — solo parejas. Si preguntan por la mejor jugadora de damas,
  aclarar que damas juegan solo dobles y los datos son de parejas, no jugadoras individuales.
  Si el usuario insiste, se puede separar por '/' pero la pareja es la unidad de medida real.

  Para calcular games ganados por JUGADOR/PAREJA usar ESTE patrón exacto (probado):
    WITH sets AS (
      SELECT pi.jugador_local, pi.jugador_visitante, pi.ganador, pi.categoria,
             unnest(string_to_array(
               regexp_replace(pi.score, '\\s*\\([^)]*\\)', '', 'g'), ', '
             )) AS set_score
      FROM partidos_individuales pi
      WHERE pi.score ~ '\\d' AND pi.score NOT ILIKE '%%WO%%' AND pi.estado = 'Finalizado'
    ),
    games AS (
      SELECT jugador_local, jugador_visitante, ganador,
             SUM(CAST(split_part(set_score,'-',1) AS INTEGER)) AS gl,
             SUM(CAST(split_part(set_score,'-',2) AS INTEGER)) AS gv
      FROM sets WHERE set_score ~ '^\\d+-\\d+$'
      GROUP BY jugador_local, jugador_visitante, ganador
    ),
    player_games AS (
      SELECT jugador_local AS jugador, SUM(gl) AS total FROM games WHERE ganador='L' GROUP BY jugador_local
      UNION ALL
      SELECT jugador_visitante, SUM(gv) FROM games WHERE ganador='V' GROUP BY jugador_visitante
    )
    SELECT jugador, SUM(total) AS games_ganados
    FROM player_games GROUP BY jugador ORDER BY games_ganados DESC LIMIT 10
  Para games POR EQUIPO usar tabla_posiciones.diferencia_games (más eficiente).

RELACIONES CLAVE:
  jugador -> equipo -> categoria -> torneo
  partido -> categoria -> torneo
  tabla_posiciones -> equipo + categoria
  partidos_individuales.id_serie -> partidos.source_serie_id (referencia, no FK estricta)
"""

# ------------------------------------------------------------
# SEGURIDAD: validacion SQL antes de ejecutar
# ------------------------------------------------------------
_FORBIDDEN = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|VACUUM|EXEC|CALL)\b",
    re.IGNORECASE,
)


def validate_and_run(sql: str) -> list:
    """Valida que el SQL sea un SELECT seguro y lo ejecuta."""
    sql = sql.strip().rstrip(";")
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.IGNORECASE):
        raise ValueError("Solo se permiten consultas SELECT")
    if _FORBIDDEN.search(sql):
        raise ValueError("La consulta contiene operaciones no permitidas")
    if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        sql += " LIMIT 100"
    # psycopg2 interpreta % como format specifier — escapar para que llegue literal a PostgreSQL
    sql = sql.replace("%", "%%")
    return query(sql)


# ------------------------------------------------------------
# MODO JSON (fallback cuando USE_DB=false)
# ------------------------------------------------------------
def build_context_from_json() -> str:
    """Construye el contexto leyendo datos desde el JSON en memoria (modo demo)."""
    data = load_json_data()
    torneos = data.get("torneos", [])

    standings_list, proximos_list, resultados_list, jugadores_list, partidos_list = [], [], [], [], []

    for t in torneos:
        torneo_nombre = t.get("torneo", "")
        categoria = t.get("categoria", "")
        anio = t.get("anio", "")
        tipo = t.get("tipo", "")

        for s in t.get("standings", []):
            standings_list.append({
                "torneo": torneo_nombre, "anio": anio, "tipo": tipo,
                "categoria": categoria, "pos": s.get("pos"), "equipo": s.get("equipo"),
                "pts": s.get("pts"), "pj": s.get("pj"), "pg": s.get("pg"),
                "pp": s.get("pp"), "sg": s.get("sg"),
                "dif_sets": s.get("dif_sets"), "dif_games": s.get("dif_games"),
            })

        for eq in t.get("equipos", []):
            equipo_nombre = eq.get("nombre", "")
            for j in eq.get("jugadores", []):
                jugadores_list.append({
                    "torneo": torneo_nombre, "anio": anio, "categoria": categoria,
                    "equipo": equipo_nombre, "jugador": j.get("nombre", ""), "edad": j.get("edad", ""),
                })

        for sr in t.get("series", []):
            estado = sr.get("estado", "PENDIENTE")
            fecha = sr.get("fecha", "")
            local = sr.get("local", "")
            visitante = sr.get("visitante", "")
            entrada = {
                "torneo": torneo_nombre, "anio": anio, "categoria": categoria,
                "fecha": fecha, "hora": sr.get("hora"),
                "local": local, "visitante": visitante,
                "score_local": sr.get("score_local", 0),
                "score_visitante": sr.get("score_visitante", 0),
                "estado": estado, "sede": sr.get("sede", ""),
            }
            if estado in ("PENDIENTE", "REPROGRAMADO"):
                proximos_list.append(entrada)
            elif estado in ("CONFIRMADO", "A CONFIRMAR"):
                resultados_list.append(entrada)

            for p in sr.get("partidos", []):
                if p.get("local") or p.get("visitante"):
                    partidos_list.append({
                        "torneo": torneo_nombre, "anio": anio, "categoria": categoria,
                        "fecha": fecha, "equipo_local": local, "equipo_visitante": visitante,
                        "tipo": p.get("tipo", ""),
                        "jugador_local": p.get("local", ""),
                        "jugador_visitante": p.get("visitante", ""),
                        "score": p.get("score", ""),
                        "ganador": "local" if p.get("ganador") == "L" else "visitante" if p.get("ganador") == "V" else p.get("ganador", ""),
                        "estado": p.get("estado", ""),
                    })

    ctx = [
        "=== TABLA DE POSICIONES ===", json.dumps(standings_list, ensure_ascii=False, default=str),
        "=== PROXIMOS PARTIDOS ===", json.dumps(proximos_list, ensure_ascii=False, default=str),
        "=== RESULTADOS DE SERIES ===", json.dumps(resultados_list, ensure_ascii=False, default=str),
        "=== JUGADORES POR EQUIPO ===", json.dumps(jugadores_list, ensure_ascii=False, default=str),
        "=== PARTIDOS INDIVIDUALES ===", json.dumps(partidos_list, ensure_ascii=False, default=str),
    ]
    return "\n".join(ctx)


def build_prompt(system: str, history: list, user_message: str) -> str:
    """Construye el prompt para modo JSON (sin function calling)."""
    parts = [system, ""]
    for msg in history:
        role = "Usuario" if msg.get("role") == "user" else "Asistente"
        parts.append(f"{role}: {msg.get('content', '')}")
    parts.append(f"Usuario: {user_message}")
    parts.append("Asistente:")
    return "\n".join(parts)

