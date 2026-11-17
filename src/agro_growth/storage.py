"""Репозитории хранения (TimescaleDB / Redis).

Импорт psycopg отложен: ядро и тесты не требуют установленного драйвера БД.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from .domain import DailyWeather, Observation

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://agro:agro@localhost:5432/agro"
)


class TelemetryRepository:
    def __init__(self, dsn: str = DATABASE_URL):
        self.dsn = dsn

    def _connect(self):
        import psycopg  # type: ignore[import-not-found]

        return psycopg.connect(self.dsn)

    def insert_telemetry(self, plot_id: str, weather: DailyWeather) -> None:
        query = """
            INSERT INTO telemetry (
                time, plot_id, tmax, tmin, rh, par_umol, photoperiod_h,
                rain_mm, irrigation_mm, soil_ph, soil_ec, qc_flag
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (time, plot_id) DO NOTHING
        """
        values = (
            datetime.combine(weather.day, datetime.min.time()),
            plot_id,
            weather.tmax,
            weather.tmin,
            weather.rh,
            weather.par_umol,
            weather.photoperiod_h,
            weather.rain_mm,
            weather.irrigation_mm,
            weather.soil_ph,
            weather.soil_ec,
            "ok",
        )
        with self._connect() as conn:
            conn.execute(query, values)

    def insert_observation(self, plot_id: str, observation: Observation) -> None:
        query = """
            INSERT INTO observations (time, plot_id, fresh_mass_g, diameter_mm, source)
            VALUES (%s, %s, %s, %s, %s)
        """
        values = (
            datetime.combine(observation.day, datetime.min.time()),
            plot_id,
            observation.fresh_mass_g,
            observation.diameter_mm,
            "sensor",
        )
        with self._connect() as conn:
            conn.execute(query, values)

    def fetch_history(self, plot_id: str, days: int = 120) -> list[DailyWeather]:
        raise NotImplementedError("Реализуется на этапе P1 вместе с живой БД")

    def save_forecast(self, plot_id: str, payload: dict[str, Any]) -> None:
        query = """
            INSERT INTO forecasts (id, plot_id, target_t_ha, p50_end, p_target, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload
        """
        series = payload.get("p50_t_ha") or [0.0]
        values = (
            payload["id"],
            plot_id,
            payload.get("target_t_ha"),
            series[-1],
            payload.get("probability_target"),
            json.dumps(payload, ensure_ascii=False),
        )
        with self._connect() as conn:
            conn.execute(query, values)


class ForecastCache:
    """TTL-кэш последнего прогноза (этап P1)."""

    def __init__(self, url: str | None = None):
        self.url = url or os.getenv("REDIS_URL", "redis://localhost:6379/0")

    def get(self, plot_id: str) -> dict[str, Any] | None:
        import redis  # type: ignore[import-not-found]

        client = redis.from_url(self.url)
        raw = client.get(f"forecast:{plot_id}")
        return json.loads(raw) if raw else None

    def set(self, plot_id: str, payload: dict[str, Any], ttl: int = 600) -> None:
        import redis  # type: ignore[import-not-found]

        client = redis.from_url(self.url)
        client.setex(f"forecast:{plot_id}", ttl, json.dumps(payload, ensure_ascii=False))
