from __future__ import annotations

import csv
import math
import threading
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from back.config import Settings, Turbine
from back.schemas import UTC


class PreparationError(Exception):
    def __init__(self, message: str, code: str = "input_unavailable", status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class WeatherValue:
    wind_speed_ms: float
    temperature_c: float
    source: str


class DatasetSeries:
    def __init__(self, values: dict[datetime, WeatherValue]):
        self.values = values
        self.times = sorted(values)

    def sample(self, timestamp: datetime, interval_minutes: int, *, observed_before: datetime | None = None) -> WeatherValue | None:
        """Preserve native 10-minute values; aggregate coarser bins or label interpolation."""
        if not self.times:
            return None
        right = timestamp + timedelta(minutes=interval_minutes)
        if observed_before is not None:
            right = min(right, observed_before)
        left_index = bisect_left(self.times, timestamp)
        right_index = bisect_left(self.times, right)
        samples = [self.values[t] for t in self.times[left_index:right_index]]
        if samples:
            return WeatherValue(
                sum(v.wind_speed_ms for v in samples) / len(samples),
                sum(v.temperature_c for v in samples) / len(samples),
                "dataset" if len(samples) == 1 else "dataset_aggregated",
            )
        # Only synthesize a finer grid between adjacent native measurements.
        # Do not bridge missing measurements or use an observation at/after the cutoff.
        if interval_minutes < 10 and 0 < left_index < len(self.times):
            lo, hi = self.times[left_index - 1], self.times[left_index]
            if hi - lo <= timedelta(minutes=10) and (observed_before is None or hi < observed_before):
                fraction = (timestamp - lo) / (hi - lo)
                a, b = self.values[lo], self.values[hi]
                return WeatherValue(
                    a.wind_speed_ms + fraction * (b.wind_speed_ms - a.wind_speed_ms),
                    a.temperature_c + fraction * (b.temperature_c - a.temperature_c),
                    "dataset_interpolated",
                )
        return None


class DatasetRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._series: dict[str, DatasetSeries] = {}
        self._lock = threading.Lock()

    def get(self, turbine: Turbine) -> DatasetSeries:
        with self._lock:
            if turbine.id not in self._series:
                self._series[turbine.id] = self._load(turbine)
            return self._series[turbine.id]

    def _load(self, turbine: Turbine) -> DatasetSeries:
        directory = self.settings.datasets_dir
        files = sorted(p for p in directory.glob("*.csv") if p.stem.lower().endswith(f"turbine {turbine.number}"))
        if len(files) != 1:
            raise PreparationError(
                f"Expected one CSV ending in 'turbine {turbine.number}.csv' in DATASETS_DIR; found {len(files)}.",
                "dataset_configuration", 503,
            )
        values: dict[datetime, WeatherValue] = {}
        counts: dict[datetime, int] = {}
        with files[0].open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            try:
                time_col = next(c for c in columns if c.strip() == "Статистическое время")
                wind_col = next(c for c in columns if c.strip().startswith("Средняя скорость ветра"))
                temp_col = next(c for c in columns if c.strip().startswith("Средняя температура окружающей среды"))
            except StopIteration as exc:
                raise PreparationError("Turbine CSV is missing its timestamp, wind, or temperature column.", "dataset_schema", 503) from exc
            for row in reader:
                try:
                    stamp = datetime.strptime(row[time_col].strip(), "%Y-%m-%d %H:%M:%S")
                    stamp = stamp.replace(tzinfo=self.settings.timezone).astimezone(UTC)
                    wind = float(row[wind_col].strip().replace(",", "."))
                    temp = float(row[temp_col].strip().replace(",", "."))
                    if not math.isfinite(wind) or not math.isfinite(temp) or wind < 0:
                        continue
                except (ValueError, TypeError, AttributeError):
                    continue
                # Deliberately do not read or propagate power/energy columns.
                old = values.get(stamp)
                count = counts.get(stamp, 0)
                if old:
                    wind = (old.wind_speed_ms * count + wind) / (count + 1)
                    temp = (old.temperature_c * count + temp) / (count + 1)
                values[stamp] = WeatherValue(wind, temp, "dataset")
                counts[stamp] = count + 1
        if not values:
            raise PreparationError("No valid weather measurements found in the turbine CSV.", "dataset_empty", 503)
        return DatasetSeries(values)
