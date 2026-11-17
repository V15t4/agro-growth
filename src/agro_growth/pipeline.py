"""Сборка конвейера: профиль культуры + данные → прогноз.

Используется и API, и CLI-демо, и фоновыми воркерами.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from .domain import CropProfile, DailyWeather, Observation, Plot, PlotState
from .forecasting import (
    ForecastResult,
    default_grids,
    fit_posterior,
    forecast,
)
from .model import GrowthModel, run_days


def compute_forecast(
    plot: Plot,
    weather_history: list[DailyWeather],
    observations: list[Observation],
    weather_future: list[DailyWeather],
    *,
    n_samples: int = 1000,
    sigma_log: float = 0.18,
    weather_sigma: float = 1.2,
    seed: int = 42,
) -> ForecastResult:
    """Полный расчёт: оценить параметры по истории и спрогнозировать урожай."""
    if not weather_history:
        raise ValueError("Требуется хотя бы один день истории погоды")
    if not weather_future:
        raise ValueError("Требуется хотя бы один день прогноза погоды")

    model = GrowthModel(plot.crop, plot.latitude_deg)
    state0 = PlotState.initial(weather_history[0].day, plot.crop)
    mu_grid, k_grid = default_grids(plot.crop)

    posterior = fit_posterior(
        model=model,
        initial_state=state0,
        weather_history=weather_history,
        observations=observations,
        mu_grid=mu_grid,
        k_grid=k_grid,
        sigma_log=sigma_log,
    )

    return forecast(
        model=model,
        state=state0,
        weather_future=weather_future,
        posterior=posterior,
        plants_per_ha=plot.plants_per_ha,
        target_t_ha=plot.crop.target_yield_t_ha,
        n_samples=n_samples,
        weather_sigma=weather_sigma,
        seed=seed,
        weather_history=weather_history,
    )


def synthetic_weather(
    start: date, days: int, seed: int = 7, latitude_deg: float = 55.75
) -> list[DailyWeather]:
    """Синтетическая агрометео-последовательность для демо и тестов."""
    rng = np.random.default_rng(seed)
    result: list[DailyWeather] = []
    for index in range(days):
        day = start + timedelta(days=index)
        doy = day.timetuple().tm_yday
        phase = 2.0 * math.pi * (doy - 110) / 365.0
        seasonal = 11.0 * math.sin(phase)
        tmax = 23.0 + seasonal + float(rng.normal(0.0, 3.0))
        tmin = tmax - 8.0 + float(rng.normal(0.0, 1.5))
        rh = float(np.clip(66.0 + rng.normal(0.0, 8.0), 30.0, 95.0))
        par = max(120.0, 480.0 + 130.0 * math.sin(phase) + float(rng.normal(0.0, 40.0)))
        photoperiod = max(8.0, 13.0 + 2.5 * math.sin(phase))
        rain = 6.0 if rng.random() < 0.12 else 0.0
        result.append(
            DailyWeather(
                day=day,
                tmax=round(tmax, 2),
                tmin=round(tmin, 2),
                rh=round(rh, 2),
                par_umol=round(par, 2),
                photoperiod_h=round(photoperiod, 2),
                rain_mm=rain,
                irrigation_mm=6.0,
            )
        )
    return result


def run_demo(config_path: str | Path | None = None) -> dict:
    """Демонстрация на синтетических данных с известными истинными параметрами."""
    if config_path is None:
        config_path = (
            Path(__file__).resolve().parents[2] / "configs" / "crops" / "tomato.yaml"
        )
    profile = CropProfile.from_yaml(config_path)
    plot = Plot(
        id="greenhouse-3",
        crop=profile,
        latitude_deg=55.75,
        plants_per_ha=20_000,
        area_m2=1000.0,
    )

    start = date(2026, 4, 1)
    history = synthetic_weather(start, 70, seed=11)
    future = synthetic_weather(start + timedelta(days=70), 40, seed=12)

    # «Истинные» параметры — генерируем наблюдаемые замеры
    true_mu, true_k = 0.086, 370.0
    model = GrowthModel(profile, plot.latitude_deg)
    _, states = run_days(
        model, PlotState.initial(start, profile), history, true_mu, true_k
    )
    measurement_days = {20, 38, 55, 69}
    observations = [
        Observation(day=states[i].day, fresh_mass_g=round(model.fruit_mass_g(states[i]), 1))
        for i in range(len(states))
        if i in measurement_days
    ]

    result = compute_forecast(
        plot=plot,
        weather_history=history,
        observations=observations,
        weather_future=future,
        n_samples=500,
        seed=3,
    )
    return {
        "plot_id": plot.id,
        "true_parameters": {"mu": true_mu, "capacity_g": true_k},
        "observations": [o.mass_g(profile) for o in observations],
        "forecast": result.to_dict(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="АгроПрогноз: демо расчёта")
    parser.add_argument("--config", type=str, default=None, help="Путь к YAML культуры")
    args = parser.parse_args()
    print(json.dumps(run_demo(args.config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
