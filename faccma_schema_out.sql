-- ============================================================
-- FACCMA TENIS - Schema MySQL
-- AWS RDS MySQL 8.0
-- ============================================================

CREATE DATABASE IF NOT EXISTS faccma_tenis CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE faccma_tenis;

-- ------------------------------------------------------------
-- 1. TORNEOS
-- ------------------------------------------------------------
CREATE TABLE torneos (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,
    tipo            ENUM('Apertura','Clausura') NOT NULL,
    anio            YEAR NOT NULL,
    id_torneo_src   INT,
    fecha_inicio    DATE,
    fecha_fin       DATE,
    activo          BOOLEAN DEFAULT FALSE,
    fecha_scraped   DATETIME,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_anio_tipo (anio, tipo)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 2. CATEGORIAS
-- ------------------------------------------------------------
CREATE TABLE categorias (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    id_torneo   INT NOT NULL,
    nombre      VARCHAR(100) NOT NULL,
    genero      ENUM('Masculino','Femenino','Mixto') NOT NULL,
    nivel       VARCHAR(50),
    zona        VARCHAR(50) DEFAULT 'UNICO',
    modalidad   VARCHAR(50),
    dia_juego   VARCHAR(50),
    id_cat_src  INT,
    id_niv_src  INT,
    FOREIGN KEY (id_torneo) REFERENCES torneos(id),
    INDEX idx_torneo (id_torneo),
    INDEX idx_nombre (nombre)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 3. INSTITUCIONES / CLUBES
-- ------------------------------------------------------------
CREATE TABLE instituciones (
    id      INT AUTO_INCREMENT PRIMARY KEY,
    nombre  VARCHAR(100) NOT NULL UNIQUE,
    sigla   VARCHAR(20),
    activa  BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 4. EQUIPOS
-- ------------------------------------------------------------
CREATE TABLE equipos (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    id_institucion  INT,
    id_torneo       INT NOT NULL,
    id_categoria    INT NOT NULL,
    nombre          VARCHAR(100) NOT NULL,
    id_equipo_src   INT,
    FOREIGN KEY (id_institucion) REFERENCES instituciones(id),
    FOREIGN KEY (id_torneo) REFERENCES torneos(id),
    FOREIGN KEY (id_categoria) REFERENCES categorias(id),
    INDEX idx_categoria (id_categoria),
    INDEX idx_nombre (nombre)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 5. JUGADORES
-- ------------------------------------------------------------
CREATE TABLE jugadores (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    id_institucion  INT,
    nombre          VARCHAR(150) NOT NULL,
    edad            INT,
    id_usr_src      INT,
    activo          BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (id_institucion) REFERENCES instituciones(id),
    INDEX idx_nombre (nombre)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 6. LISTA DE BUENA FE (jugador en equipo/torneo)
-- ------------------------------------------------------------
CREATE TABLE lista_buena_fe (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    id_equipo   INT NOT NULL,
    id_jugador  INT NOT NULL,
    orden       INT,
    designacion VARCHAR(10),
    FOREIGN KEY (id_equipo) REFERENCES equipos(id),
    FOREIGN KEY (id_jugador) REFERENCES jugadores(id),
    UNIQUE KEY uq_equipo_jugador (id_equipo, id_jugador),
    INDEX idx_equipo (id_equipo)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 7. STANDINGS (tabla de posiciones)
-- ------------------------------------------------------------
CREATE TABLE standings (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    id_categoria    INT NOT NULL,
    id_equipo       INT NOT NULL,
    posicion        INT,
    puntos          INT DEFAULT 0,
    series_jugadas  INT DEFAULT 0,
    series_ganadas  INT DEFAULT 0,
    series_empatadas INT DEFAULT 0,
    series_perdidas INT DEFAULT 0,
    parciales_favor INT DEFAULT 0,
    parciales_contra INT DEFAULT 0,
    dif_sets        VARCHAR(10),
    dif_games       VARCHAR(10),
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (id_categoria) REFERENCES categorias(id),
    FOREIGN KEY (id_equipo) REFERENCES equipos(id),
    UNIQUE KEY uq_cat_equipo (id_categoria, id_equipo),
    INDEX idx_categoria_pos (id_categoria, posicion)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 8. SERIES (enfrentamientos entre equipos)
-- ------------------------------------------------------------
CREATE TABLE series (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    id_serie_src    INT,
    id_categoria    INT NOT NULL,
    id_equipo_local INT NOT NULL,
    id_equipo_visit INT NOT NULL,
    fecha           DATE,
    hora            TIME,
    sede            VARCHAR(150),
    score_local     INT DEFAULT 0,
    score_visitante INT DEFAULT 0,
    estado          ENUM('PENDIENTE','CONFIRMADO','A CONFIRMAR','REPROGRAMADO','WO') DEFAULT 'PENDIENTE',
    FOREIGN KEY (id_categoria) REFERENCES categorias(id),
    FOREIGN KEY (id_equipo_local) REFERENCES equipos(id),
    FOREIGN KEY (id_equipo_visit) REFERENCES equipos(id),
    INDEX idx_categoria (id_categoria),
    INDEX idx_fecha (fecha),
    INDEX idx_local (id_equipo_local),
    INDEX idx_visitante (id_equipo_visit)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 9. PARTIDOS (singles y dobles dentro de cada serie)
-- ------------------------------------------------------------
CREATE TABLE partidos (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    id_serie    INT NOT NULL,
    tipo        VARCHAR(20),
    local       VARCHAR(100),
    visitante   VARCHAR(100),
    score       VARCHAR(50),
    ganador     ENUM('L','V','WO') DEFAULT NULL,
    estado      VARCHAR(30),
    FOREIGN KEY (id_serie) REFERENCES series(id),
    INDEX idx_serie (id_serie)
) ENGINE=InnoDB;

-- ============================================================
-- VISTAS UTILES
-- ============================================================

-- Vista: posiciones con nombres
CREATE OR REPLACE VIEW v_standings AS
SELECT
    t.nombre AS torneo, t.anio, t.tipo,
    cat.nombre AS categoria, cat.genero,
    s.posicion, e.nombre AS equipo,
    s.puntos, s.series_jugadas, s.series_ganadas,
    s.parciales_favor, s.dif_sets, s.dif_games
FROM standings s
JOIN categorias cat ON s.id_categoria = cat.id
JOIN torneos t ON cat.id_torneo = t.id
JOIN equipos e ON s.id_equipo = e.id
ORDER BY t.anio DESC, t.tipo, cat.nombre, s.posicion;

-- Vista: proximos partidos
CREATE OR REPLACE VIEW v_proximos AS
SELECT
    t.nombre AS torneo, cat.nombre AS categoria,
    sr.fecha, sr.hora,
    el.nombre AS local, sr.score_local,
    ev.nombre AS visitante, sr.score_visitante,
    sr.estado, sr.sede
FROM series sr
JOIN categorias cat ON sr.id_categoria = cat.id
JOIN torneos t ON cat.id_torneo = t.id
JOIN equipos el ON sr.id_equipo_local = el.id
JOIN equipos ev ON sr.id_equipo_visit = ev.id
WHERE sr.estado IN ('PENDIENTE','REPROGRAMADO')
ORDER BY sr.fecha, sr.hora;

-- Vista: resultados confirmados
CREATE OR REPLACE VIEW v_resultados AS
SELECT
    t.nombre AS torneo, t.anio, cat.nombre AS categoria,
    sr.fecha, el.nombre AS local,
    sr.score_local, sr.score_visitante,
    ev.nombre AS visitante, sr.estado
FROM series sr
JOIN categorias cat ON sr.id_categoria = cat.id
JOIN torneos t ON cat.id_torneo = t.id
JOIN equipos el ON sr.id_equipo_local = el.id
JOIN equipos ev ON sr.id_equipo_visit = ev.id
WHERE sr.estado IN ('CONFIRMADO','A CONFIRMAR')
ORDER BY sr.fecha DESC;

