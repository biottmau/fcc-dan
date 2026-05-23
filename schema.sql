BEGIN;

CREATE TYPE estado_partido AS ENUM (
    'A CONFIRMAR',
    'CONFIRMADO',
    'PENDIENTE',
    'REPROGRAMADO'
);

CREATE TABLE torneos (
    torneo_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_torneo_id  BIGINT NOT NULL UNIQUE,
    nombre            VARCHAR(150) NOT NULL,
    fecha_generacion  DATE NOT NULL,
    fuente            TEXT
);

CREATE TABLE categorias (
    categoria_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    torneo_id            BIGINT NOT NULL REFERENCES torneos(torneo_id) ON DELETE CASCADE,
    source_categoria_id  BIGINT NOT NULL,
    source_nivel_id      BIGINT,
    nombre               VARCHAR(150) NOT NULL,
    UNIQUE (torneo_id, nombre)
);

CREATE TABLE equipos (
    equipo_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    categoria_id      BIGINT NOT NULL REFERENCES categorias(categoria_id) ON DELETE CASCADE,
    source_equipo_id  VARCHAR(30) NOT NULL,
    nombre            VARCHAR(150) NOT NULL,
    UNIQUE (categoria_id, source_equipo_id),
    UNIQUE (categoria_id, nombre)
);

CREATE TABLE jugadores (
    jugador_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    equipo_id     BIGINT NOT NULL REFERENCES equipos(equipo_id) ON DELETE CASCADE,
    nombre        VARCHAR(150) NOT NULL,
    edad          SMALLINT CHECK (edad BETWEEN 0 AND 120),
    UNIQUE (equipo_id, nombre)
);

CREATE TABLE tabla_posiciones (
    tabla_posicion_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    categoria_id        BIGINT NOT NULL REFERENCES categorias(categoria_id) ON DELETE CASCADE,
    equipo_id           BIGINT NOT NULL REFERENCES equipos(equipo_id) ON DELETE CASCADE,
    posicion            SMALLINT NOT NULL CHECK (posicion > 0),
    series_jugadas      SMALLINT NOT NULL DEFAULT 0 CHECK (series_jugadas >= 0),
    series_ganadas      SMALLINT NOT NULL DEFAULT 0 CHECK (series_ganadas >= 0),
    parciales_favor     SMALLINT NOT NULL DEFAULT 0 CHECK (parciales_favor >= 0),
    diferencia_sets     INTEGER NOT NULL DEFAULT 0,
    diferencia_games    INTEGER NOT NULL DEFAULT 0,
    puntos              SMALLINT NOT NULL DEFAULT 0 CHECK (puntos >= 0),
    UNIQUE (categoria_id, posicion),
    UNIQUE (categoria_id, equipo_id)
);

CREATE TABLE partidos (
    partido_id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    categoria_id          BIGINT NOT NULL REFERENCES categorias(categoria_id) ON DELETE CASCADE,
    source_serie_id       BIGINT NOT NULL,
    fecha                 DATE,
    hora                  TIME,
    local_nombre          VARCHAR(150) NOT NULL,
    visitante_nombre      VARCHAR(150) NOT NULL,
    local_equipo_id       BIGINT REFERENCES equipos(equipo_id) ON DELETE SET NULL,
    visitante_equipo_id   BIGINT REFERENCES equipos(equipo_id) ON DELETE SET NULL,
    score_text            VARCHAR(15),
    sets_local            SMALLINT CHECK (sets_local BETWEEN 0 AND 9),
    sets_visitante        SMALLINT CHECK (sets_visitante BETWEEN 0 AND 9),
    estado                estado_partido NOT NULL,
    sede                  VARCHAR(150),
    UNIQUE (categoria_id, source_serie_id),
    CHECK (
        local_equipo_id IS NULL
        OR visitante_equipo_id IS NULL
        OR local_equipo_id <> visitante_equipo_id
    )
);

CREATE INDEX idx_categorias_torneo          ON categorias(torneo_id);
CREATE INDEX idx_equipos_categoria          ON equipos(categoria_id);
CREATE INDEX idx_jugadores_equipo           ON jugadores(equipo_id);
CREATE INDEX idx_tabla_posiciones_categoria ON tabla_posiciones(categoria_id, posicion);
CREATE INDEX idx_partidos_categoria_fecha   ON partidos(categoria_id, fecha, hora);

COMMIT;
