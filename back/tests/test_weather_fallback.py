import asyncio
from datetime import datetime, timedelta

import httpx
import pytest

from back.config import Settings, TURBINES
from back.dataset import DatasetSeries, PreparationError, WeatherValue
from back.inputs import InputBuilder
from back.schemas import TicketRequest, UTC
from back.weather import OpenMeteo


def weather_response(request):
    assert request.url.params["timezone"] == "UTC"
    assert request.url.params["wind_speed_unit"] == "ms"
    start = datetime.fromisoformat(request.url.params["start_date"])
    end = datetime.fromisoformat(request.url.params["end_date"]) + timedelta(days=1)
    hours = [start + timedelta(hours=i) for i in range(int((end - start).total_seconds() / 3600))]
    hourly = {"time": [h.isoformat() for h in hours]}
    units = {}
    for variable in request.url.params["hourly"].split(","):
        hourly[variable] = [float(h.hour + 1) for h in hours]
        units[variable] = "m/s" if variable.startswith("wind") else "°C"
    return httpx.Response(200, json={"hourly": hourly, "hourly_units": units})


@pytest.mark.parametrize("year", [2023, 2024])
def test_missing_context_and_horizon_use_era5_preserving_local_rows(tmp_path, year):
    settings = Settings(cache_dir=tmp_path, turbine_timezone="UTC")
    origin = datetime(year, 3, 11, tzinfo=UTC)
    # Most weather is absent, including all history before the archive starts.
    class Dataset:
        def get(self, turbine):
            return DatasetSeries({origin: WeatherValue(99, 25, "dataset")})

    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "archive-api.open-meteo.com"
        assert request.url.params["models"] == "era5"
        assert request.url.params["hourly"] == "wind_speed_100m,temperature_2m"
        return weather_response(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            builder = InputBuilder(settings, Dataset(), OpenMeteo(settings, client))
            request = TicketRequest(turbine_id="A", horizon_start=origin, history_days=7)
            rows = await builder.build(request, now=datetime(2026, 9, 23, tzinfo=UTC))
            assert await builder.build(request, now=datetime(2026, 9, 23, tzinfo=UTC)) == rows
            assert len(rows) == (168 + 48) * 6
            local = [r for r in rows if r["weather_source"] == "dataset"]
            assert len(local) == 1
            assert local[0]["wind_speed_ms"] == 99
            for phase in ("history", "forecast"):
                assert any(r["phase"] == phase and r["weather_source"].startswith("open_meteo_reanalysis_era5") for r in rows)
            assert rows[1]["wind_speed_ms"] == pytest.approx(1 + 1 / 6, abs=1e-6)
            assert all("power" not in k for row in rows for k in row)

    asyncio.run(run())
    assert len(calls) == 1  # Repeat uses the persistent weather cache.


def test_recent_weather_and_future_keep_forecast_routes(tmp_path):
    now = datetime(2026, 9, 23, tzinfo=UTC)
    stamps = [now - timedelta(days=7), now - timedelta(days=1), now + timedelta(hours=1)]
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return weather_response(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await OpenMeteo(Settings(cache_dir=tmp_path), client).weather_for(
                TURBINES["A"], stamps, horizon_start=now, now=now,
            )
            assert result[stamps[0]].source == "open_meteo_reanalysis_era5"
            assert result[stamps[1]].source.startswith("open_meteo_archive_d")
            assert result[stamps[2]].source == "open_meteo_live"

    asyncio.run(run())
    assert set(calls) == {"archive-api.open-meteo.com", "previous-runs-api.open-meteo.com", "api.open-meteo.com"}


@pytest.mark.parametrize("bad", ["null", "units", "height"])
def test_historical_fallback_does_not_invent_unavailable_weather(tmp_path, bad):
    def handler(request):
        payload = weather_response(request).json()
        if bad == "null":
            payload["hourly"]["wind_speed_100m"][0] = None
        if bad == "units":
            payload["hourly_units"]["wind_speed_100m"] = "km/h"
        return httpx.Response(200, json=payload)

    async def run():
        settings = Settings(cache_dir=tmp_path, wind_variable="wind_speed_80m" if bad == "height" else "wind_speed_100m")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(PreparationError) as caught:
                await OpenMeteo(settings, client).weather_for(
                    TURBINES["A"], [datetime(2023, 3, 11, tzinfo=UTC)],
                    horizon_start=datetime(2023, 3, 11, tzinfo=UTC), now=datetime(2026, 9, 23, tzinfo=UTC),
                )
            assert caught.value.code == ("historical_weather_configuration" if bad == "height" else "weather_unavailable")

    asyncio.run(run())
