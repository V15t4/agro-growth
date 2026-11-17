"""Чистые математические зависимости роста.

Правило модуля: только ``math`` и числа. Никакого I/O, состояния и случайности —
благодаря этому формулы можно проверять на эталонных значениях и вызывать
из Jupyter, API и batch-воркера одинаково.
"""

from __future__ import annotations

import math
from typing import Iterable


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Ограничить значение интервалом."""
    return max(low, min(high, value))


def mean_temp(tmax: float, tmin: float) -> float:
    return (tmax + tmin) / 2.0


def saturation_vapour_pressure(temp_c: float) -> float:
    """Давление насыщенного водяного пара, кПа (FAO-56, Tetens)."""
    return 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))


def vapor_pressure_deficit(temp_c: float, rh_pct: float) -> float:
    """Дефицит давления водяного пара, кПа."""
    rh = clamp(rh_pct, 0.0, 100.0)
    return saturation_vapour_pressure(temp_c) * (1.0 - rh / 100.0)


def extraterrestrial_radiation(day_of_year: int, latitude_deg: float) -> float:
    """Внеземная солнечная радиация, МДж/м²/сут (FAO-56, приложение 2)."""
    lat = math.radians(latitude_deg)
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * day_of_year / 365.0)
    delta = 0.409 * math.sin(2.0 * math.pi * day_of_year / 365.0 - 1.39)
    cos_ws = -math.tan(lat) * math.tan(delta)
    ws = math.acos(clamp(cos_ws, -1.0, 1.0))
    daily = (
        24.0
        * 60.0
        / math.pi
        * 0.0820
        * dr
        * (
            ws * math.sin(lat) * math.sin(delta)
            + math.cos(lat) * math.cos(delta) * math.sin(ws)
        )
    )
    return max(daily, 0.0)


def hargreaves_et0(
    tmax: float, tmin: float, day_of_year: int, latitude_deg: float
) -> float:
    """Эталонная эвапотранспирация Hargreaves, мм/сут."""
    t_avg = mean_temp(tmax, tmin)
    dtr = max(tmax - tmin, 0.0)
    ra = extraterrestrial_radiation(day_of_year, latitude_deg)
    return max(0.0, 0.0023 * ra * (t_avg + 17.8) * math.sqrt(dtr))


def growing_degree_days(
    tmax: float, tmin: float, t_base: float, t_upper: float | None = None
) -> float:
    """Сумма эффективных температур за сутки, °C·сут."""
    t_avg = mean_temp(tmax, tmin)
    if t_upper is not None:
        t_avg = min(t_avg, t_upper)
    return max(t_avg - t_base, 0.0)


def dli(par_umol: float, photoperiod_h: float) -> float:
    """Дневная интегральная световая доза, моль/м²/сут."""
    return max(par_umol, 0.0) * max(photoperiod_h, 0.0) * 3600.0 / 1e6


def par_mj(par_umol: float, photoperiod_h: float) -> float:
    """Фотосинтетически активная радиация, МДж/м²/сут."""
    return dli(par_umol, photoperiod_h) * 0.235


def light_interception(lai: float, k_extinction: float = 0.5) -> float:
    """Доля поглощённого света по закону Бира — Ламберта — Бугера."""
    return 1.0 - math.exp(-k_extinction * max(lai, 0.0))


def trapezoid_stress(
    value: float,
    opt_low: float,
    opt_high: float,
    crit_low: float,
    crit_high: float,
) -> float:
    """Трапециевидная функция пригодности: 0 → 1 → 0."""
    if value <= crit_low or value >= crit_high:
        return 0.0
    if value < opt_low:
        return clamp((value - crit_low) / max(opt_low - crit_low, 1e-9))
    if value > opt_high:
        return clamp((crit_high - value) / max(crit_high - opt_high, 1e-9))
    return 1.0


def vpd_stress(vpd_kpa: float, opt_low: float, opt_high: float, critical: float) -> float:
    """Стресс по дефициту влажности воздуха."""
    if vpd_kpa <= opt_low:
        return clamp(vpd_kpa / max(opt_low, 1e-9))
    if vpd_kpa <= opt_high:
        return 1.0
    return clamp((critical - vpd_kpa) / max(critical - opt_high, 1e-9))


def ph_stress(ph: float, opt_low: float, opt_high: float, tolerance: float) -> float:
    """Стресс по кислотности почвы."""
    return trapezoid_stress(
        ph, opt_low, opt_high, opt_low - tolerance, opt_high + tolerance
    )


def ec_stress(ec: float, threshold: float, slope: float) -> float:
    """Стресс по засолению (пороговая модель Мааса — Хоффмана)."""
    return clamp(1.0 - max(ec - threshold, 0.0) / max(slope, 1e-9))


def water_stress_coeff(
    theta: float,
    theta_fc: float,
    theta_wp: float,
    root_depth_mm: float,
    depletion_fraction: float = 0.5,
) -> float:
    """Коэффициент водного стресса Ks по FAO-56."""
    taw = max(theta_fc - theta_wp, 1e-6) * root_depth_mm
    raw = depletion_fraction * taw
    depletion = (theta_fc - theta) * root_depth_mm
    if depletion <= raw:
        return 1.0
    return clamp((taw - depletion) / max(taw - raw, 1e-9))


def soil_water_balance(
    theta_prev: float,
    input_mm: float,
    etc_mm: float,
    root_depth_mm: float,
    theta_fc: float,
) -> float:
    """Простой баланс влаги в корневом слое с дренажом выше ПВ."""
    theta = theta_prev + (input_mm - etc_mm) / max(root_depth_mm, 1.0)
    return min(theta, theta_fc)


def logistic_increment(biomass_g: float, mu: float, capacity_g: float) -> float:
    """Потенциальный прирост биомассы по логистическому закону."""
    k = max(capacity_g, 1e-6)
    if biomass_g >= k:
        return 0.0
    w = clamp(biomass_g, 1e-6, k * 0.999999)
    return max(mu * w * (1.0 - w / k), 0.0)


def radiation_increment(
    par_umol: float,
    photoperiod_h: float,
    lai: float,
    k_extinction: float,
    rue: float,
) -> float:
    """Радиационно ограниченный прирост сухой биомассы, г."""
    apar = par_mj(par_umol, photoperiod_h) * light_interception(lai, k_extinction)
    return max(rue * apar, 0.0)


def combine_stress(factors: Iterable[float]) -> float:
    """Итоговый стресс как произведение независимых факторов."""
    result = 1.0
    for factor in factors:
        result *= clamp(factor)
    return clamp(result)


def fruit_fresh_mass_g(
    dry_biomass_g: float, harvest_index: float, dry_matter_fraction: float
) -> float:
    """Свежая масса плодов с растения, г."""
    return max(dry_biomass_g, 0.0) * harvest_index / max(dry_matter_fraction, 1e-6)


def yield_t_per_ha(fresh_mass_g_per_plant: float, plants_per_ha: int) -> float:
    """Урожайность, т/га."""
    return fresh_mass_g_per_plant * plants_per_ha / 1e6
