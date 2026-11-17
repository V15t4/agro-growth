"""Детерминированная пошаговая модель роста.

Один вызов ``advance`` = один день. Модель не знает про байесовский вывод и API:
она получает параметры ``mu`` и ``K`` извне и возвращает новое состояние.
"""

from __future__ import annotations

import math
from dataclasses import replace

from .domain import CropProfile, DailyWeather, PlotState
from . import formulas as f


class GrowthModel:
    def __init__(self, profile: CropProfile, latitude_deg: float):
        self.profile = profile
        self.latitude_deg = latitude_deg

    # ------------------------------------------------------------------
    # Диагностика (используется и для расчёта, и для объяснения прогноза)
    # ------------------------------------------------------------------
    def kc(self, gdd: float) -> float:
        """Коэффициент транспирации как функция фенологического этапа."""
        p = self.profile
        stage = f.clamp(gdd / max(p.gdd_to_maturity, 1e-6))
        if stage < 0.3:
            return p.kc_ini + (p.kc_mid - p.kc_ini) * (stage / 0.3)
        if stage < 0.8:
            return p.kc_mid
        return p.kc_mid + (p.kc_end - p.kc_mid) * ((stage - 0.8) / 0.2)

    def factors(self, weather: DailyWeather, state: PlotState) -> dict[str, float]:
        """Отдельные стресс-факторы за день, каждый в [0, 1]."""
        p = self.profile
        t_avg = f.mean_temp(weather.tmax, weather.tmin)
        vpd = f.vapor_pressure_deficit(weather.tmax, weather.rh)
        return {
            "temperature": f.trapezoid_stress(
                t_avg, p.t_opt_lo, p.t_opt_hi, p.t_crit_lo, p.t_crit_hi
            ),
            "vpd": f.vpd_stress(vpd, p.vpd_opt_lo, p.vpd_opt_hi, p.vpd_critical),
            "water": f.water_stress_coeff(
                state.theta,
                p.theta_fc,
                p.theta_wp,
                p.root_depth_mm,
                p.depletion_fraction,
            ),
            "ph": f.ph_stress(
                weather.soil_ph
                if weather.soil_ph is not None
                else (p.ph_opt_lo + p.ph_opt_hi) / 2.0,
                p.ph_opt_lo,
                p.ph_opt_hi,
                p.ph_tolerance,
            ),
            "ec": f.ec_stress(
                weather.soil_ec
                if weather.soil_ec is not None
                else p.ec_threshold,
                p.ec_threshold,
                p.ec_slope,
            ),
        }

    # ------------------------------------------------------------------
    # Шаг модели
    # ------------------------------------------------------------------
    def advance(
        self, state: PlotState, weather: DailyWeather, mu: float, capacity_g: float
    ) -> PlotState:
        p = self.profile
        factors = self.factors(weather, state)
        stress = f.combine_stress(factors.values())

        gdd = f.growing_degree_days(weather.tmax, weather.tmin, p.t_base, p.t_upper)
        gdd_new = state.gdd + gdd

        day_of_year = weather.day.timetuple().tm_yday
        et0 = f.hargreaves_et0(
            weather.tmax, weather.tmin, day_of_year, self.latitude_deg
        )
        etc = et0 * self.kc(state.gdd) * factors["water"]
        theta_new = f.soil_water_balance(
            state.theta,
            weather.rain_mm + weather.irrigation_mm,
            etc,
            p.root_depth_mm,
            p.theta_fc,
        )

        growth_potential = f.logistic_increment(state.dry_biomass_g, mu, capacity_g)
        growth_radiation = f.radiation_increment(
            weather.par_umol,
            weather.photoperiod_h,
            state.lai,
            p.k_extinction,
            p.rue,
        )
        increment = min(growth_potential, growth_radiation) * stress

        # Листовая поверхность растёт по фенологической шкале (GDD),
        # а не напрямую от прироста биомассы — иначе затенение «душит» модель
        # на ранних этапах, когда растения ещё маленькие.
        lai_scale = 1.2 / max(p.lai_gain, 1e-6)
        lai_target = p.lai_max / (1.0 + math.exp(-(gdd_new - 250.0) / lai_scale))
        lai_new = min(p.lai_max, max(state.lai, lai_target))
        biomass_new = max(state.dry_biomass_g + increment, 1e-6)

        return replace(
            state,
            day=weather.day,
            theta=theta_new,
            lai=lai_new,
            dry_biomass_g=biomass_new,
            gdd=gdd_new,
            cum_etc_mm=state.cum_etc_mm + etc,
        )

    # ------------------------------------------------------------------
    # Перевод состояния в наблюдаемые величины
    # ------------------------------------------------------------------
    def fruit_mass_g(self, state: PlotState) -> float:
        p = self.profile
        return f.fruit_fresh_mass_g(
            state.dry_biomass_g, p.harvest_index, p.dry_matter_fraction
        )

    def yield_t_per_ha(self, state: PlotState, plants_per_ha: int) -> float:
        return f.yield_t_per_ha(self.fruit_mass_g(state), plants_per_ha)


def run_days(
    model: GrowthModel,
    state: PlotState,
    weather_days: list[DailyWeather],
    mu: float,
    capacity_g: float,
) -> tuple[PlotState, list[PlotState]]:
    """Прогнать модель по последовательности дней, вернуть историю состояний."""
    history: list[PlotState] = []
    current = state
    for day_weather in weather_days:
        current = model.advance(current, day_weather, mu, capacity_g)
        history.append(current)
    return current, history
