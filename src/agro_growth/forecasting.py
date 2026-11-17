"""Байесовский вывод параметров и вероятностный прогноз урожая.

Схема: сетка (μ, K) → правдоподобие наблюдений → апостериорные веса →
ансамбль сценариев с шумом погоды → квантили и вероятность цели.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date

import numpy as np

from .domain import CropProfile, DailyWeather, Observation, PlotState
from .model import GrowthModel


@dataclass
class Posterior:
    """Дискретное апостериорное распределение параметров (μ, K)."""

    mu_grid: np.ndarray
    k_grid: np.ndarray
    weights: np.ndarray  # форма: (len(mu_grid), len(k_grid))

    def sample(self, rng: np.random.Generator, size: int) -> tuple[np.ndarray, np.ndarray]:
        flat = rng.choice(self.weights.size, size=size, p=self.weights.ravel())
        mu_idx, k_idx = np.unravel_index(flat, self.weights.shape)
        return self.mu_grid[mu_idx], self.k_grid[k_idx]

    @property
    def mean_mu(self) -> float:
        return float((self.weights.sum(axis=1) * self.mu_grid).sum())

    @property
    def mean_k(self) -> float:
        return float((self.weights.sum(axis=0) * self.k_grid).sum())


@dataclass
class ForecastResult:
    days: list[date]
    p10_t_ha: list[float]
    p50_t_ha: list[float]
    p90_t_ha: list[float]
    probability_target: float
    diagnostics: dict[str, float]
    n_samples: int
    target_t_ha: float

    def to_dict(self) -> dict:
        return {
            "days": [d.isoformat() for d in self.days],
            "p10_t_ha": [round(x, 3) for x in self.p10_t_ha],
            "p50_t_ha": [round(x, 3) for x in self.p50_t_ha],
            "p90_t_ha": [round(x, 3) for x in self.p90_t_ha],
            "probability_target": round(self.probability_target, 4),
            "diagnostics": {k: round(v, 3) for k, v in self.diagnostics.items()},
            "n_samples": self.n_samples,
            "target_t_ha": self.target_t_ha,
        }


def default_grids(profile: CropProfile, size: int = 21) -> tuple[np.ndarray, np.ndarray]:
    """Априорные сетки вокруг справочных значений культуры."""
    mu_grid = np.linspace(profile.mu_prior * 0.5, profile.mu_prior * 1.5, size)
    k_grid = np.linspace(profile.k_prior_g * 0.6, profile.k_prior_g * 1.4, size)
    return mu_grid, k_grid


def fit_posterior(
    model: GrowthModel,
    initial_state: PlotState,
    weather_history: list[DailyWeather],
    observations: list[Observation],
    mu_grid: np.ndarray,
    k_grid: np.ndarray,
    sigma_log: float = 0.18,
) -> Posterior:
    """Оценить распределение (μ, K) по истории замеров.

    При отсутствии наблюдений возвращается равномерный априор на сетке —
    это корректное поведение для «холодного старта» участка.
    """
    obs_by_day = {obs.day: obs for obs in observations}
    loglik = np.zeros((len(mu_grid), len(k_grid)), dtype=float)
    profile = model.profile

    for i, mu in enumerate(mu_grid):
        for j, capacity in enumerate(k_grid):
            state = replace(initial_state)
            score = 0.0
            for weather in weather_history:
                state = model.advance(state, weather, float(mu), float(capacity))
                obs = obs_by_day.get(weather.day)
                if obs is None:
                    continue
                predicted = model.fruit_mass_g(state)
                observed = obs.mass_g(profile)
                if predicted <= 0.0 or observed <= 0.0:
                    continue
                residual = (math.log(observed) - math.log(predicted)) / sigma_log
                score += -0.5 * residual * residual
            loglik[i, j] = score

    shifted = loglik - loglik.max()
    weights = np.exp(shifted)
    total = weights.sum()
    if total <= 0.0 or not np.isfinite(total):
        weights = np.ones_like(weights) / weights.size
    else:
        weights /= total

    return Posterior(mu_grid=np.asarray(mu_grid), k_grid=np.asarray(k_grid), weights=weights)


def _perturb_weather(
    weather: DailyWeather, rng: np.random.Generator, sigma: float
) -> DailyWeather:
    """Добавить шум к прогнозу погоды для ансамбля сценариев."""
    if sigma <= 0.0:
        return weather
    return replace(
        weather,
        tmax=weather.tmax + float(rng.normal(0.0, sigma)),
        tmin=weather.tmin + float(rng.normal(0.0, sigma)),
        rh=float(np.clip(weather.rh + rng.normal(0.0, sigma * 2.0), 5.0, 100.0)),
    )


def forecast(
    model: GrowthModel,
    state: PlotState,
    weather_future: list[DailyWeather],
    posterior: Posterior,
    plants_per_ha: int,
    target_t_ha: float,
    n_samples: int = 2000,
    weather_sigma: float = 1.2,
    seed: int = 42,
    weather_history: list[DailyWeather] | None = None,
) -> ForecastResult:
    """Сгенерировать ансамбль прогнозов и вернуть квантили.

    Каждый сценарий сначала воспроизводит наблюдаемую историю с выбранными
    (μ, K) — без шума погоды, — затем продолжается зашумлённым прогнозом.
    Это сохраняет связь между оценёнными параметрами и текущим состоянием.
    """
    if not weather_future:
        raise ValueError("weather_future не может быть пустым")

    rng = np.random.default_rng(seed)
    mus, capacities = posterior.sample(rng, n_samples)
    samples = np.empty((n_samples, len(weather_future)), dtype=float)
    last_state = state

    for sample_idx in range(n_samples):
        current = replace(state)
        mu = float(mus[sample_idx])
        capacity = float(capacities[sample_idx])

        # Воспроизведение прошлого: известная погода, неизвестные параметры
        for past_weather in weather_history or []:
            current = model.advance(current, past_weather, mu, capacity)

        for day_idx, weather in enumerate(weather_future):
            current = model.advance(
                current, _perturb_weather(weather, rng, weather_sigma), mu, capacity
            )
            samples[sample_idx, day_idx] = model.yield_t_per_ha(current, plants_per_ha)

        last_state = current

    p10, p50, p90 = np.percentile(samples, [10, 50, 90], axis=0)
    probability = float(np.mean(samples[:, -1] >= target_t_ha))

    last_weather = weather_future[-1]
    diagnostics = model.factors(last_weather, last_state)

    return ForecastResult(
        days=[w.day for w in weather_future],
        p10_t_ha=p10.tolist(),
        p50_t_ha=p50.tolist(),
        p90_t_ha=p90.tolist(),
        probability_target=probability,
        diagnostics=diagnostics,
        n_samples=n_samples,
        target_t_ha=target_t_ha,
    )
