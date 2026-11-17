"""Юнит-тесты математического ядра (stdlib unittest, без pytest)."""

from __future__ import annotations

import math
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from agro_growth import formulas as f  # noqa: E402
from agro_growth.domain import CropProfile, DailyWeather, Observation, PlotState  # noqa: E402
from agro_growth.forecasting import default_grids, fit_posterior  # noqa: E402
from agro_growth.model import GrowthModel, run_days  # noqa: E402
from agro_growth.pipeline import synthetic_weather  # noqa: E402

CONFIG = Path(__file__).resolve().parents[1] / "configs" / "crops" / "tomato.yaml"


class FormulaTests(unittest.TestCase):
    def test_growing_degree_days(self):
        self.assertAlmostEqual(f.growing_degree_days(25, 15, 10), 10.0)
        self.assertAlmostEqual(f.growing_degree_days(8, 6, 10), 0.0)
        self.assertAlmostEqual(f.growing_degree_days(40, 38, 10, 32), 22.0)

    def test_vpd(self):
        # e_s(20 °C) ≈ 2.338 кПа → VPD при RH 50 % ≈ 1.169 кПа
        self.assertAlmostEqual(f.saturation_vapour_pressure(20.0), 2.338, places=3)
        self.assertAlmostEqual(f.vapor_pressure_deficit(20.0, 50.0), 1.169, places=3)

    def test_radiation_seasonality(self):
        summer = f.extraterrestrial_radiation(172, 55.75)
        winter = f.extraterrestrial_radiation(355, 55.75)
        self.assertGreater(summer, winter * 2)
        self.assertGreater(f.hargreaves_et0(25, 15, 172, 55.75), 0.0)

    def test_water_stress_bounds(self):
        kwargs = dict(theta_fc=0.32, theta_wp=0.12, root_depth_mm=400)
        self.assertEqual(f.water_stress_coeff(theta=0.32, **kwargs), 1.0)
        self.assertEqual(f.water_stress_coeff(theta=0.12, **kwargs), 0.0)
        partial = f.water_stress_coeff(theta=0.18, **kwargs)
        self.assertTrue(0.0 < partial < 1.0)

    def test_stress_is_bounded(self):
        for value in (-10, 0, 5, 20, 100):
            self.assertTrue(0.0 <= f.vpd_stress(value, 0.5, 1.2, 2.5) <= 1.0)
        self.assertEqual(f.combine_stress([1.0, 0.5, 0.0]), 0.0)

    def test_logistic_increment(self):
        inc = f.logistic_increment(100.0, 0.08, 350.0)
        self.assertAlmostEqual(inc, 0.08 * 100 * (1 - 100 / 350))
        self.assertEqual(f.logistic_increment(350.0, 0.08, 350.0), 0.0)

    def test_light_and_yield(self):
        self.assertTrue(0.0 < f.light_interception(3.0, 0.55) < 1.0)
        self.assertAlmostEqual(f.dli(500, 12), 21.6)
        self.assertAlmostEqual(f.yield_t_per_ha(3000, 20_000), 60.0)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.profile = CropProfile.from_yaml(CONFIG)
        self.model = GrowthModel(self.profile, 55.75)

    def test_monotonic_biomass_and_bounded_stresses(self):
        weather = synthetic_weather(date(2026, 4, 1), 40, seed=5)
        state = PlotState.initial(weather[0].day, self.profile)
        previous = state.dry_biomass_g
        for day in weather:
            factors = self.model.factors(day, state)
            self.assertTrue(all(0.0 <= v <= 1.0 for v in factors.values()))
            state = self.model.advance(state, day, 0.08, 350.0)
            self.assertGreaterEqual(state.dry_biomass_g, previous)
            previous = state.dry_biomass_g
        self.assertLessEqual(state.theta, self.profile.theta_fc + 1e-9)
        self.assertLessEqual(state.lai, self.profile.lai_max + 1e-9)

    def test_kc_stages(self):
        self.assertAlmostEqual(self.model.kc(0), self.profile.kc_ini)
        self.assertAlmostEqual(
            self.model.kc(self.profile.gdd_to_maturity * 0.5), self.profile.kc_mid
        )
        self.assertAlmostEqual(
            self.model.kc(self.profile.gdd_to_maturity), self.profile.kc_end
        )


class ForecastTests(unittest.TestCase):
    def test_posterior_normalized_and_recovers_parameters(self):
        profile = CropProfile.from_yaml(CONFIG)
        model = GrowthModel(profile, 55.75)
        weather = synthetic_weather(date(2026, 4, 1), 70, seed=11)
        true_mu, true_k = 0.086, 370.0
        _, states = run_days(
            model, PlotState.initial(weather[0].day, profile), weather, true_mu, true_k
        )
        observations = [
            Observation(day=states[i].day, fresh_mass_g=model.fruit_mass_g(states[i]))
            for i in (20, 38, 55, 69)
        ]
        mu_grid, k_grid = default_grids(profile)
        posterior = fit_posterior(
            model,
            PlotState.initial(weather[0].day, profile),
            weather,
            observations,
            mu_grid,
            k_grid,
        )
        self.assertAlmostEqual(float(posterior.weights.sum()), 1.0, places=8)
        self.assertLess(abs(posterior.mean_mu - true_mu), 0.01)
        self.assertLess(abs(posterior.mean_k - true_k), 40.0)

    def test_demo_forecast_shape(self):
        from agro_growth.pipeline import run_demo

        demo = run_demo()
        forecast = demo["forecast"]
        self.assertEqual(len(forecast["days"]), 40)
        self.assertEqual(len(forecast["p50_t_ha"]), 40)
        for lo, mid, hi in zip(
            forecast["p10_t_ha"], forecast["p50_t_ha"], forecast["p90_t_ha"]
        ):
            self.assertLessEqual(lo, mid)
            self.assertLessEqual(mid, hi)
        self.assertTrue(0.0 <= forecast["probability_target"] <= 1.0)


if __name__ == "__main__":
    unittest.main()
