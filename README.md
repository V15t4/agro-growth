# АгроПрогноз

Вероятностный прогноз роста и урожая плодовых культур и овощей по данным о состоянии
растений/почвы/погоды и математическим моделям.

Полная архитектура, формулы и дорожная карта: **[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Что уже работает (этап P0)

- Чистое математическое ядро: GDD, VPD, ET0 (Hargreaves), водный баланс, Ks,
  световой интеграл, fPAR/RUE, стресс-факторы, логистический рост, урожай.
- Байесовская оценка скрытых параметров `(μ, K)` по замерам массы/диаметра.
- Монте-Карло ансамбль с шумом прогноза погоды → `P10 / P50 / P90` и
  вероятность достижения целевой урожайности.
- Справочник культур в YAML (сейчас — томат).
- FastAPI-контракты, MQTT-инжест, схема TimescaleDB, Docker Compose, React-скелет.
- 11 юнит-тестов на эталонных значениях и синтетике.

## Быстрый старт

```bash
cd agro-growth
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate

pip install -r requirements/dev.txt

# Тесты
python -m unittest discover -s tests -v

# Демо (синтетическая погода + 4 замера + прогноз на 40 дней)
set PYTHONPATH=src          # Windows PowerShell: $env:PYTHONPATH='src'
python -m agro_growth.pipeline
```

## Запуск сервисов

```bash
docker compose up -d --build
# API:       http://localhost:8000/docs
# frontend: http://localhost:5173
```

## Пример запроса к API

```bash
curl -X POST http://localhost:8000/v1/forecast \
  -H 'Content-Type: application/json' \
  -d '{
    "plot": {"id": "g3", "crop_id": "tomato", "latitude_deg": 55.75,
             "plants_per_ha": 20000},
    "weather_history": [{"day": "2026-05-01", "tmax": 24, "tmin": 14,
                         "rh": 65, "par_umol": 500, "photoperiod_h": 13}],
    "observations": [{"day": "2026-05-01", "fresh_mass_g": 120}],
    "weather_future": [{"day": "2026-05-02", "tmax": 25, "tmin": 15,
                        "rh": 60, "par_umol": 520, "photoperiod_h": 13}],
    "n_samples": 500
  }'
```

## Структура

```text
src/agro_growth/
  domain.py       — типы и загрузчик YAML
  formulas.py     — чистые формулы (без I/O)
  model.py        — детерминированный пошаговый рост
  forecasting.py  — байес + Монте-Карло
  pipeline.py     — сборка расчёта и CLI-демо
  api.py          — FastAPI
  ingestion.py    — MQTT → валидация → БД
  storage.py      — TimescaleDB / Redis репозитории
```
