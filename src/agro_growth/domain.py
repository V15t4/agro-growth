"""Типы предметной области и загрузчик справочника культур."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class CropProfile:
    """Физиологические параметры культуры.

    Все значения заданы для одной единицы площади/растения.
    Единицы указаны в ARCHITECTURE.md, раздел 3.
    """

    id: str
    name: str
    t_base: float
    t_upper: float
    gdd_to_maturity: float
    kc_ini: float
    kc_mid: float
    kc_end: float
    vpd_opt_lo: float
    vpd_opt_hi: float
    vpd_critical: float
    t_opt_lo: float
    t_opt_hi: float
    t_crit_lo: float
    t_crit_hi: float
    ph_opt_lo: float
    ph_opt_hi: float
    ph_tolerance: float
    ec_threshold: float
    ec_slope: float
    theta_fc: float
    theta_wp: float
    root_depth_mm: float
    depletion_fraction: float
    lai_max: float
    lai_gain: float
    k_extinction: float
    rue: float
    harvest_index: float
    dry_matter_fraction: float
    fruit_allometry_a: float
    fruit_allometry_b: float
    target_yield_t_ha: float
    mu_prior: float
    k_prior_g: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CropProfile":
        names = {f.name for f in fields(cls)}
        unknown = set(data) - names
        if unknown:
            raise ValueError(f"Неизвестные параметры культуры: {sorted(unknown)}")
        missing = names - set(data)
        if missing:
            raise ValueError(f"Отсутствуют параметры культуры: {sorted(missing)}")
        return cls(**data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "CropProfile":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Ожидался YAML-словарь в файле {path}")
        return cls.from_mapping(raw)


@dataclass(frozen=True)
class DailyWeather:
    """Один агрометео-день."""

    day: date
    tmax: float
    tmin: float
    rh: float
    par_umol: float
    photoperiod_h: float
    rain_mm: float = 0.0
    irrigation_mm: float = 0.0
    soil_ph: float | None = None
    soil_ec: float | None = None


@dataclass(frozen=True)
class Observation:
    """Замер растения: масса плода или диаметр (пересчитывается аллометрией)."""

    day: date
    fresh_mass_g: float | None = None
    diameter_mm: float | None = None

    def mass_g(self, profile: CropProfile) -> float:
        if self.fresh_mass_g is not None:
            return float(self.fresh_mass_g)
        if self.diameter_mm is not None:
            return (
                profile.fruit_allometry_a
                * float(self.diameter_mm) ** profile.fruit_allometry_b
            )
        raise ValueError("Observation должен содержать fresh_mass_g или diameter_mm")


@dataclass
class PlotState:
    """Динамическое состояние участка/растения на дату ``day``."""

    day: date
    theta: float
    lai: float
    dry_biomass_g: float
    gdd: float
    cum_etc_mm: float = 0.0

    @classmethod
    def initial(cls, day: date, profile: CropProfile) -> "PlotState":
        return cls(
            day=day,
            theta=profile.theta_fc * 0.85,
            lai=0.05,
            dry_biomass_g=5.0,
            gdd=0.0,
        )


@dataclass(frozen=True)
class Plot:
    """Участок: привязка культуры, география и густота стояния."""

    id: str
    crop: CropProfile
    latitude_deg: float
    plants_per_ha: int
    area_m2: float = 0.0
