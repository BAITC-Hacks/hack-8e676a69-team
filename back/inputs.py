from __future__ import annotations

import asyncio
import csv
import os
from datetime import datetime
from pathlib import Path

from back.config import Settings, TURBINES
from back.dataset import DatasetRepository, WeatherValue
from back.schemas import TicketRequest
from back.weather import OpenMeteo

CSV_COLUMNS = ("timestamp", "phase", "turbine_id", "wind_speed_ms", "temperature_c", "weather_source")


class InputBuilder:
    def __init__(self, settings: Settings, datasets: DatasetRepository, weather: OpenMeteo):
        self.settings = settings
        self.datasets = datasets
        self.weather = weather

    async def build(self, request: TicketRequest, *, now: datetime) -> list[dict]:
        turbine = TURBINES[request.turbine_id]
        series = await asyncio.to_thread(self.datasets.get, turbine)
        horizon = request.start_utc(self.settings.timezone)
        stamps = request.timestamps(self.settings.timezone)
        values: dict[datetime, WeatherValue] = {}
        for stamp in stamps:
            history = stamp < horizon
            if history or self.settings.use_dataset_for_horizon:
                value = series.sample(stamp, request.interval_minutes, observed_before=horizon if history else None)
                if value is not None:
                    values[stamp] = value
        missing = [stamp for stamp in stamps if stamp not in values]
        values.update(await self.weather.weather_for(turbine, missing, horizon_start=horizon, now=now))
        return [
            {
                "timestamp": stamp.astimezone(self.settings.timezone).isoformat(timespec="seconds"),
                "phase": "history" if stamp < horizon else "forecast",
                "turbine_id": turbine.id,
                "wind_speed_ms": round(values[stamp].wind_speed_ms, 6),
                "temperature_c": round(values[stamp].temperature_c, 6),
                "weather_source": values[stamp].source,
            }
            for stamp in stamps
        ]


def publish_csv(ticket_dir: Path, rows: list[dict]) -> None:
    """data.csv appears only after the complete weather-only input is durable."""
    temporary = ticket_dir / "data.csv.tmp"
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, ticket_dir / "data.csv")
