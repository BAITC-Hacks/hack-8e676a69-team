from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime, timedelta

import httpx

from back.config import Settings, Turbine
from back.dataset import PreparationError, WeatherValue
from back.schemas import UTC

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_URL = "https://archive-api.open-meteo.com/v1/archive"


def forecast_lead_days(valid_time: datetime, cutoff: datetime, margin_hours: int) -> int:
    """Choose an older archived lead so its estimated availability is <= cutoff.

    Open-Meteo's fixed lead offsets are not exact publication timestamps.
    The configurable margin is deliberately conservative, not a proven run SLA.
    """
    hours = (valid_time - cutoff).total_seconds() / 3600
    lead = max(1, math.ceil((hours + margin_hours) / 24))
    if lead > 7:
        raise PreparationError("Requested replay needs a weather lead beyond the archive's seven-day offsets.", "forecast_out_of_range")
    return lead


class OpenMeteo:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def weather_for(self, turbine: Turbine, timestamps: list[datetime], *, horizon_start: datetime, now: datetime) -> dict[datetime, WeatherValue]:
        if not timestamps:
            return {}
        hours: set[datetime] = set()
        for stamp in timestamps:
            floor = stamp.replace(minute=0, second=0, microsecond=0)
            hours.add(floor)
            if stamp != floor:
                hours.add(floor + timedelta(hours=1))
        # A replay earlier than now must not consume the current forecast,
        # including when some target hours are still in the future today.
        allow_live = horizon_start >= now
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        live_hours = {h for h in hours if allow_live and h >= current_hour}
        # ERA5 has a publication delay of about five days. Leave six complete
        # UTC days for availability. Reanalysis is recorded-weather replay,
        # not a forecast that was available at the historical horizon start.
        historical_before = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        historical_hours = {
            h for h in hours
            if h < historical_before and self.settings.use_historical_weather
        }
        archived_hours = hours - live_hours - historical_hours
        cutoff = min(horizon_start, now)
        values: dict[datetime, WeatherValue] = {}
        calls = []
        if historical_hours:
            calls.append(self._historical(turbine, sorted(historical_hours)))
        if archived_hours:
            calls.append(self._archived(turbine, sorted(archived_hours), cutoff))
        if live_hours:
            if max(live_hours).date() > (now + timedelta(days=15)).date():
                raise PreparationError("Live weather is only available within the provider's next 16 calendar days.", "forecast_out_of_range")
            calls.append(self._live(turbine, sorted(live_hours)))
        for result in await asyncio.gather(*calls):
            values.update(result)
        output = {}
        for stamp in timestamps:
            lo = stamp.replace(minute=0, second=0, microsecond=0)
            a = values[lo]
            if stamp == lo:
                output[stamp] = a
                continue
            b = values[lo + timedelta(hours=1)]
            fraction = (stamp - lo).total_seconds() / 3600
            sources = a.source if a.source == b.source else f"{a.source}+{b.source}"
            output[stamp] = WeatherValue(
                a.wind_speed_ms + fraction * (b.wind_speed_ms - a.wind_speed_ms),
                a.temperature_c + fraction * (b.temperature_c - a.temperature_c),
                sources + "_interpolated",
            )
        return output

    def _params(self, turbine: Turbine, hours: list[datetime]) -> dict:
        return {
            "latitude": turbine.latitude,
            "longitude": turbine.longitude,
            "start_date": min(hours).date().isoformat(),
            "end_date": max(hours).date().isoformat(),
            "models": self.settings.weather_model,
            "timezone": "UTC",
            "wind_speed_unit": "ms",
            "temperature_unit": "celsius",
        }

    async def _archived(self, turbine: Turbine, hours: list[datetime], cutoff: datetime) -> dict[datetime, WeatherValue]:
        leads = {h: forecast_lead_days(h, cutoff, self.settings.forecast_availability_margin_hours) for h in hours}
        variables = [f"{v}_previous_day{d}" for d in sorted(set(leads.values())) for v in (self.settings.wind_variable, "temperature_2m")]
        params = self._params(turbine, hours)
        params["hourly"] = ",".join(variables)
        payload = await self._get_json(PREVIOUS_RUNS_URL, params, ttl=86400)
        index = self._time_index(payload)
        return {
            h: self._value(payload, index, h,
                f"{self.settings.wind_variable}_previous_day{leads[h]}",
                f"temperature_2m_previous_day{leads[h]}",
                f"open_meteo_archive_d{leads[h]}")
            for h in hours
        }

    async def _historical(self, turbine: Turbine, hours: list[datetime]) -> dict[datetime, WeatherValue]:
        if self.settings.wind_variable not in {"wind_speed_10m", "wind_speed_100m"}:
            raise PreparationError(
                "ERA5 historical weather supports wind at 10m or 100m; configure WEATHER_WIND_VARIABLE accordingly.",
                "historical_weather_configuration", 503,
            )
        params = self._params(turbine, hours)
        params["models"] = "era5"
        params["hourly"] = f"{self.settings.wind_variable},temperature_2m"
        payload = await self._get_json(HISTORICAL_URL, params, ttl=86400 * 30)
        index = self._time_index(payload)
        return {
            h: self._value(payload, index, h, self.settings.wind_variable, "temperature_2m", "open_meteo_reanalysis_era5")
            for h in hours
        }

    async def _live(self, turbine: Turbine, hours: list[datetime]) -> dict[datetime, WeatherValue]:
        params = self._params(turbine, hours)
        params["hourly"] = f"{self.settings.wind_variable},temperature_2m"
        payload = await self._get_json(FORECAST_URL, params, ttl=300)
        index = self._time_index(payload)
        return {h: self._value(payload, index, h, self.settings.wind_variable, "temperature_2m", "open_meteo_live") for h in hours}

    @staticmethod
    def _time_index(payload: dict) -> dict[datetime, int]:
        try:
            return {datetime.fromisoformat(t).replace(tzinfo=UTC): i for i, t in enumerate(payload["hourly"]["time"])}
        except (KeyError, TypeError, ValueError) as exc:
            raise PreparationError("Weather provider returned an invalid hourly time axis.", "weather_response_invalid", 502) from exc

    @staticmethod
    def _value(payload: dict, index: dict, hour: datetime, wind_key: str, temp_key: str, source: str) -> WeatherValue:
        try:
            i = index[hour]
            wind = float(payload["hourly"][wind_key][i])
            temp = float(payload["hourly"][temp_key][i])
            if not math.isfinite(wind) or not math.isfinite(temp) or wind < 0:
                raise ValueError("non-finite weather")
            units = payload.get("hourly_units", {})
            if units.get(wind_key) != "m/s" or units.get(temp_key) not in {"°C", "C"}:
                raise ValueError("unexpected weather units")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise PreparationError(
                f"No usable wind/temperature weather data for {hour.isoformat()}. Choose another date or verify provider coverage and units.",
                "weather_unavailable", 422,
            ) from exc
        return WeatherValue(wind, temp, source)

    async def _get_json(self, url: str, params: dict, ttl: int) -> dict:
        cache_key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        cache_file = self.settings.cache_dir / f"{cache_key}.json"
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if 0 <= time.time() - cached["fetched_at"] < ttl:
                return cached["payload"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        for attempt in range(3):
            try:
                response = await self.client.get(url, params=params, timeout=self.settings.weather_timeout_seconds)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or "hourly" not in payload:
                    raise ValueError("missing hourly data")
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 400:
                    raise PreparationError("Weather provider rejected this date range or weather configuration.", "weather_request_rejected", 422) from exc
                if exc.response.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise PreparationError("Weather provider is unavailable; retry this ticket later.", "weather_service_unavailable", 502) from exc
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise PreparationError("Weather request failed or timed out; retry this ticket later.", "weather_service_unavailable", 502) from exc
            except ValueError as exc:
                raise PreparationError("Weather provider returned invalid JSON data.", "weather_response_invalid", 502) from exc
            await asyncio.sleep(0.5 * (attempt + 1))
        try:
            self.settings.cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = cache_file.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temporary.write_text(json.dumps({"fetched_at": time.time(), "payload": payload}), encoding="utf-8")
            os.replace(temporary, cache_file)
        except OSError:
            # Weather remains usable if the optional cache cannot be written.
            pass
        return payload
