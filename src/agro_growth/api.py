"""HTTP API: FastAPI + Pydantic v2.

Запуск:  uvicorn agro_growth.api:app --reload
Документация: /docs
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .domain import CropProfile, DailyWeather, Observation, Plot
from .pipeline import compute_forecast

app = FastAPI(title="АгроПрогноз", version="0.1.0")

CROP_DIR = Path(os.getenv("CROP_CONFIG_DIR", "configs/crops"))
_FORECASTS: dict[str, dict[str, Any]] = {}
_OBSERVATIONS: dict[str, list[Observation]] = {}


# ----------------------------------------------------------------------
# Pydantic-контракты
# ----------------------------------------------------------------------
class WeatherIn(BaseModel):
    day: date
    tmax: float
    tmin: float
    rh: float = Field(ge=0, le=100)
    par_umol: float = Field(ge=0)
    photoperiod_h: float = Field(ge=0, le=24)
    rain_mm: float = 0.0
    irrigation_mm: float = 0.0
    soil_ph: float | None = None
    soil_ec: float | None = None

    def to_domain(self) -> DailyWeather:
        return DailyWeather(**self.model_dump())


class ObservationIn(BaseModel):
    day: date
    fresh_mass_g: float | None = Field(default=None, ge=0)
    diameter_mm: float | None = Field(default=None, ge=0)

    def to_domain(self) -> Observation:
        return Observation(**self.model_dump())


class PlotIn(BaseModel):
    id: str
    crop_id: str
    latitude_deg: float = Field(ge=-90, le=90)
    plants_per_ha: int = Field(gt=0)
    area_m2: float = 0.0


class ForecastRequest(BaseModel):
    plot: PlotIn
    weather_history: list[WeatherIn] = Field(min_length=1)
    observations: list[ObservationIn] = Field(default_factory=list)
    weather_future: list[WeatherIn] = Field(min_length=1)
    n_samples: int = Field(default=1000, ge=50, le=10_000)
    weather_sigma: float = Field(default=1.2, ge=0, le=10)


# ----------------------------------------------------------------------
# Вспомогательные функции
# ----------------------------------------------------------------------
def _load_crop(crop_id: str) -> CropProfile:
    path = CROP_DIR / f"{crop_id}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Культура '{crop_id}' не найдена")
    return CropProfile.from_yaml(path)


def _build_plot(plot_in: PlotIn) -> Plot:
    return Plot(
        id=plot_in.id,
        crop=_load_crop(plot_in.crop_id),
        latitude_deg=plot_in.latitude_deg,
        plants_per_ha=plot_in.plants_per_ha,
        area_m2=plot_in.area_m2,
    )


# ----------------------------------------------------------------------
# Маршруты
# ----------------------------------------------------------------------
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/crops")
def list_crops() -> list[dict[str, str]]:
    if not CROP_DIR.exists():
        return []
    return [
        {"id": p.stem, "name": CropProfile.from_yaml(p).name}
        for p in sorted(CROP_DIR.glob("*.yaml"))
    ]


@app.post("/v1/observations", status_code=201)
def add_observation(plot_id: str, observation: ObservationIn) -> dict[str, int]:
    stored = _OBSERVATIONS.setdefault(plot_id, [])
    stored.append(observation.to_domain())
    return {"count": len(stored)}


@app.post("/v1/forecast")
def create_forecast(request: ForecastRequest) -> dict[str, Any]:
    plot = _build_plot(request.plot)
    observations = [o.to_domain() for o in request.observations]
    observations.extend(_OBSERVATIONS.get(plot.id, []))

    result = compute_forecast(
        plot=plot,
        weather_history=[w.to_domain() for w in request.weather_history],
        observations=observations,
        weather_future=[w.to_domain() for w in request.weather_future],
        n_samples=request.n_samples,
        weather_sigma=request.weather_sigma,
    )
    payload = {"id": str(uuid.uuid4()), "plot_id": plot.id, **result.to_dict()}
    _FORECASTS[payload["id"]] = payload
    return payload


@app.get("/v1/forecasts/{forecast_id}")
def get_forecast(forecast_id: str) -> dict[str, Any]:
    payload = _FORECASTS.get(forecast_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Прогноз не найден")
    return payload


@app.get("/v1/plots/{plot_id}/latest")
def latest_forecast(plot_id: str) -> dict[str, Any]:
    matches = [f for f in _FORECASTS.values() if f["plot_id"] == plot_id]
    if not matches:
        raise HTTPException(status_code=404, detail="Для участка нет прогнозов")
    return matches[-1]


@app.websocket("/v1/plots/{plot_id}/stream")
async def forecast_stream(websocket: WebSocket, plot_id: str) -> None:
    """Простой push-канал: при подключении и по запросу 'refresh' отдаёт прогноз."""
    await websocket.accept()
    try:
        while True:
            matches = [f for f in _FORECASTS.values() if f["plot_id"] == plot_id]
            await websocket.send_json(
                {"type": "forecast", "data": matches[-1] if matches else None}
            )
            await websocket.receive_text()
    except WebSocketDisconnect:
        return
