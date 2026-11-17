"""MQTT-инжест: приём телеметрии, валидация, нормализация, запись.

Топик: agro/{plot_id}/telemetry
Payload: {ts, tmax, tmin, rh, par_umol, photoperiod_h, soil_theta, soil_ph, soil_ec}
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from .domain import DailyWeather
from .storage import TelemetryRepository

log = logging.getLogger(__name__)

TOPIC_PREFIX = "agro/"
TELEMETRY_SUFFIX = "/telemetry"

# Допустимые диапазоны датчиков (грубая защита от неверных единиц)
RANGES: dict[str, tuple[float, float]] = {
    "tmax": (-40.0, 60.0),
    "tmin": (-40.0, 60.0),
    "rh": (0.0, 100.0),
    "par_umol": (0.0, 3000.0),
    "photoperiod_h": (0.0, 24.0),
    "rain_mm": (0.0, 500.0),
    "irrigation_mm": (0.0, 500.0),
    "soil_ph": (0.0, 14.0),
    "soil_ec": (0.0, 20.0),
}


class ValidationError(ValueError):
    pass


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Проверить и привести сообщение датчика к внутреннему виду."""
    if "ts" not in payload:
        raise ValidationError("Отсутствует поле ts")
    try:
        moment = datetime.fromisoformat(str(payload["ts"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"Неверный формат ts: {payload['ts']}") from exc

    normalized: dict[str, Any] = {"day": moment.date(), "qc_flag": "ok"}
    for field, (low, high) in RANGES.items():
        if field not in payload or payload[field] is None:
            continue
        try:
            value = float(payload[field])
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Поле {field} не число") from exc
        if not low <= value <= high:
            raise ValidationError(f"Поле {field} вне диапазона [{low}, {high}]: {value}")
        normalized[field] = value

    if "tmax" in normalized and "tmin" in normalized:
        if normalized["tmin"] > normalized["tmax"]:
            raise ValidationError("tmin не может быть больше tmax")
    return normalized


def to_weather(normalized: dict[str, Any]) -> DailyWeather:
    """Собрать DailyWeather из нормализованного сообщения."""
    required = ("tmax", "tmin", "rh", "par_umol", "photoperiod_h")
    missing = [field for field in required if field not in normalized]
    if missing:
        raise ValidationError(f"Отсутствуют обязательные поля: {missing}")
    return DailyWeather(
        day=normalized["day"],
        tmax=normalized["tmax"],
        tmin=normalized["tmin"],
        rh=normalized["rh"],
        par_umol=normalized["par_umol"],
        photoperiod_h=normalized["photoperiod_h"],
        rain_mm=normalized.get("rain_mm", 0.0),
        irrigation_mm=normalized.get("irrigation_mm", 0.0),
        soil_ph=normalized.get("soil_ph"),
        soil_ec=normalized.get("soil_ec"),
    )


class MqttBridge:
    """Мост MQTT → TimescaleDB. Зависимости импортируются лениво."""

    def __init__(self, broker: str, port: int = 1883, repository: TelemetryRepository | None = None):
        self.broker = broker
        self.port = port
        self.repository = repository or TelemetryRepository()

    def on_message(self, client: Any, userdata: Any, message: Any) -> None:
        topic = message.topic
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            if not topic.startswith(TOPIC_PREFIX) or not topic.endswith(TELEMETRY_SUFFIX):
                raise ValidationError(f"Неожиданный топик: {topic}")
            plot_id = topic[len(TOPIC_PREFIX) : -len(TELEMETRY_SUFFIX)]
            if not plot_id:
                raise ValidationError("Пустой plot_id")

            normalized = normalize_payload(payload)
            self.repository.insert_telemetry(plot_id, to_weather(normalized))
            log.info("telemetry saved: %s %s", plot_id, normalized["day"])
        except (ValidationError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("rejected message from %s: %s", topic, exc)

    def run_forever(self) -> None:
        import paho.mqtt.client as mqtt  # type: ignore[import-not-found]

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_message = self.on_message
        client.connect(self.broker, self.port, keepalive=60)
        client.subscribe("agro/+/telemetry")
        client.loop_forever()


if __name__ == "__main__":
    import os

    logging.basicConfig(level=logging.INFO)
    MqttBridge(os.getenv("MQTT_BROKER", "localhost")).run_forever()
