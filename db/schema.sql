-- Схема TimescaleDB для АгроПрогноза
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS crops (
  id   TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  config JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS plots (
  id            TEXT PRIMARY KEY,
  crop_id       TEXT NOT NULL REFERENCES crops(id),
  latitude      REAL NOT NULL,
  longitude     REAL NOT NULL,
  area_m2       REAL NOT NULL,
  plants_per_ha INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS telemetry (
  time          TIMESTAMPTZ NOT NULL,
  plot_id       TEXT NOT NULL REFERENCES plots(id),
  tmax          REAL,
  tmin          REAL,
  rh            REAL,
  par_umol      REAL,
  photoperiod_h REAL,
  rain_mm       REAL,
  irrigation_mm REAL,
  soil_theta    REAL,
  soil_ph       REAL,
  soil_ec       REAL,
  qc_flag       TEXT DEFAULT 'ok',
  PRIMARY KEY (time, plot_id)
);

SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS telemetry_plot_time_idx ON telemetry (plot_id, time DESC);

CREATE TABLE IF NOT EXISTS observations (
  time         TIMESTAMPTZ NOT NULL,
  plot_id      TEXT NOT NULL REFERENCES plots(id),
  fresh_mass_g REAL,
  diameter_mm  REAL,
  source       TEXT DEFAULT 'manual',
  PRIMARY KEY (time, plot_id)
);

SELECT create_hypertable('observations', 'time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS forecasts (
  id          UUID PRIMARY KEY,
  plot_id     TEXT NOT NULL REFERENCES plots(id),
  created_at  TIMESTAMPTZ DEFAULT now(),
  target_t_ha REAL,
  p50_end     REAL,
  p_target    REAL,
  payload     JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS forecasts_plot_time_idx ON forecasts (plot_id, created_at DESC);

-- Сжатие и retention
ALTER TABLE telemetry SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'plot_id'
);
SELECT add_compression_policy('telemetry', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('telemetry', INTERVAL '5 years', if_not_exists => TRUE);
