import asyncio
import csv
import json
import os
import time
from datetime import datetime, timedelta
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from back.config import Settings, TURBINES
from back.dataset import DatasetRepository, DatasetSeries, WeatherValue
from back.inputs import CSV_COLUMNS, InputBuilder
from back.main import create_app
from back.schemas import TicketRequest, UTC
from back.weather import OpenMeteo, forecast_lead_days


def settings_for(tmp_path, **kwargs):
    return Settings(tickets_dir=tmp_path / "tickets", datasets_dir=tmp_path / "datasets", cache_dir=tmp_path / "cache", web_dist=tmp_path / "no-web", turbine_timezone="UTC", **kwargs)


class MemoryDatasets:
    def __init__(self, values):
        self.series = DatasetSeries(values)

    def get(self, turbine):
        return self.series


class FakeWeather:
    def __init__(self):
        self.requested = []

    async def weather_for(self, turbine, timestamps, *, horizon_start, now):
        self.requested.extend(timestamps)
        return {t: WeatherValue(7.0, 3.0, "test_internet") for t in timestamps}


def test_february_fifth_window_preserves_native_samples_and_fills_gap(tmp_path):
    settings = settings_for(tmp_path)
    request = TicketRequest(turbine_id="A", horizon_start="2026-02-05", history_days=30, step=6)
    start = datetime(2026, 1, 6, tzinfo=UTC)
    end = datetime(2026, 2, 1, tzinfo=UTC)
    values = {}
    t = start
    n = 0
    while t < end:
        values[t] = WeatherValue(2.0 + n % 6, -1.0 + n % 3, "dataset")
        n += 1
        t += timedelta(minutes=10)
    weather = FakeWeather()
    rows = asyncio.run(InputBuilder(settings, MemoryDatasets(values), weather).build(request, now=datetime(2026, 9, 23, tzinfo=UTC)))
    assert len(rows) == 4608
    assert sum(r["phase"] == "history" for r in rows) == 4320
    assert sum(r["phase"] == "forecast" for r in rows) == 288
    assert rows[0]["timestamp"] == "2026-01-06T00:00:00+00:00"
    assert rows[4319]["timestamp"] == "2026-02-04T23:50:00+00:00"
    assert rows[4320]["timestamp"] == "2026-02-05T00:00:00+00:00"
    assert rows[-1]["timestamp"] == "2026-02-06T23:50:00+00:00"
    assert [r["wind_speed_ms"] for r in rows[:6]] == [2, 3, 4, 5, 6, 7]
    assert len(weather.requested) == (4 * 24 + 48) * 6
    assert min(weather.requested) == end
    assert set(rows[0]) == set(CSV_COLUMNS)
    assert not any("power" in key.lower() or "mwh" in key.lower() for key in rows[0])


def test_dataset_weather_is_optional_for_prediction_rows(tmp_path):
    settings = settings_for(tmp_path)
    horizon = datetime(2026, 1, 10, tzinfo=UTC)
    values = {horizon + timedelta(minutes=i * 10): WeatherValue(99, 99, "dataset") for i in range(144)}
    provider = FakeWeather()
    request = TicketRequest(turbine_id="B", horizon_start=horizon, history_days=1, step=6)
    rows = asyncio.run(InputBuilder(replace(settings, use_dataset_for_horizon=False), MemoryDatasets(values), provider).build(request, now=datetime(2026, 9, 23, tzinfo=UTC)))
    assert all(r["wind_speed_ms"] == 7 for r in rows if r["phase"] == "forecast")
    rows = asyncio.run(InputBuilder(settings, MemoryDatasets(values), provider).build(request, now=datetime(2026, 9, 23, tzinfo=UTC)))
    assert all(r["wind_speed_ms"] == 99 for r in rows if r["phase"] == "forecast" and r["weather_source"] == "dataset")
    assert sum(r["weather_source"] == "dataset" for r in rows) == 144


def test_dataset_loader_ignores_energy_and_timezone_is_explicit(tmp_path):
    settings = settings_for(tmp_path)
    settings.datasets_dir.mkdir()
    source = settings.datasets_dir / "sample - turbine 1.csv"
    source.write_text("ID,Статистическое время,Средняя скорость ветра(m/s),Нормализованная активная мощность,Средняя температура окружающей среды(°C)\n1,2026-01-06 0:00:00,4.5,DO_NOT_SEND,2.1\n2,2026-01-06 0:10:00,5.5,ALSO_PRIVATE,3.1\n", encoding="utf-8")
    series = DatasetRepository(settings).get(TURBINES["A"])
    stamp = datetime(2026, 1, 6, tzinfo=UTC)
    assert series.sample(stamp, 10).wind_speed_ms == 4.5
    assert series.sample(stamp, 60).wind_speed_ms == 5.0
    assert series.sample(stamp + timedelta(minutes=5), 5).source == "dataset_interpolated"
    assert series.sample(stamp + timedelta(minutes=5), 5, observed_before=stamp + timedelta(minutes=10)) is None


@pytest.mark.parametrize("step,minutes", [(1, 60), (3, 20), (6, 10), (12, 5)])
def test_sampling_definition(step, minutes):
    request = TicketRequest(turbine_id=1, horizon_start="2026-02-05", step=step)
    assert request.interval_minutes == minutes
    assert request.turbine_id == "A"


@pytest.mark.parametrize("field,value", [("step", 0), ("step", 7), ("horizon_hours", 72), ("history_days", 0), ("turbine_id", "C"), ("horizon_start", "2026-02-05T00:03:00")])
def test_invalid_requests(field, value):
    payload = {"turbine_id": "A", "horizon_start": "2026-02-05", field: value}
    with pytest.raises(ValidationError):
        TicketRequest(**payload)


def test_forecast_leads_respect_common_cutoff_including_interpolation_neighbor():
    cutoff = datetime(2026, 2, 5, tzinfo=UTC)
    for offset in range(-96, 49):
        valid = cutoff + timedelta(hours=offset)
        lead = forecast_lead_days(valid, cutoff, 12)
        assert valid - timedelta(days=lead) + timedelta(hours=12) <= cutoff
    assert forecast_lead_days(cutoff + timedelta(hours=47), cutoff, 12) == 3


def test_archive_is_resampled_honestly_and_reused_from_cache(tmp_path):
    settings = settings_for(tmp_path)
    cutoff = datetime(2026, 2, 5, tzinfo=UTC)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "previous-runs-api.open-meteo.com"
        assert request.url.params["wind_speed_unit"] == "ms"
        assert request.url.params["timezone"] == "UTC"
        start = datetime.fromisoformat(request.url.params["start_date"]).replace(tzinfo=UTC)
        end = datetime.fromisoformat(request.url.params["end_date"]).replace(tzinfo=UTC) + timedelta(days=1)
        hours = [start + timedelta(hours=i) for i in range(int((end - start).total_seconds() // 3600))]
        hourly = {"time": [h.strftime("%Y-%m-%dT%H:%M") for h in hours]}
        units = {"time": "iso8601"}
        for variable in request.url.params["hourly"].split(","):
            hourly[variable] = [float(h.hour) for h in hours]
            units[variable] = "m/s" if variable.startswith("wind") else "°C"
        return httpx.Response(200, json={"hourly": hourly, "hourly_units": units})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenMeteo(settings, client)
            timestamp = cutoff + timedelta(hours=1, minutes=10)
            result = await provider.weather_for(TURBINES["A"], [timestamp], horizon_start=cutoff, now=datetime(2026, 9, 23, tzinfo=UTC))
            again = await provider.weather_for(TURBINES["A"], [timestamp], horizon_start=cutoff, now=datetime(2026, 9, 23, tzinfo=UTC))
            assert result == again
            assert result[timestamp].wind_speed_ms == pytest.approx(1 + 1 / 6)
            assert result[timestamp].source.endswith("_interpolated")
    asyncio.run(run())
    assert len(calls) == 1


def wait_for_input(client, ticket_id, ticket_dir):
    for _ in range(200):
        response = client.get(f"/api/tickets/{ticket_id}")
        assert response.status_code == 202, response.text
        if (ticket_dir / "data.csv").exists():
            return
        time.sleep(0.01)
    pytest.fail("CSV was not published")


def test_http_folder_handoff_and_opaque_ml_output_survive_backend_restart(tmp_path):
    settings = settings_for(tmp_path)
    repository = MemoryDatasets({})
    app = create_app(settings, datasets=repository, weather=FakeWeather())
    with TestClient(app) as client:
        response = client.post("/api/tickets", json={"turbine_id": "B", "horizon_start": "2026-02-05", "history_days": 1, "step": 6})
        assert response.status_code == 202
        ticket_id = response.json()["ticket_id"]
        ticket_dir = settings.tickets_dir / ticket_id
        wait_for_input(client, ticket_id, ticket_dir)
        assert {p.name for p in ticket_dir.iterdir()} == {"data.csv"}
        with (ticket_dir / "data.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 432
        assert all(r["turbine_id"] == "B" for r in rows)
        # A fixture reply verifies transport only; it is not a real ML prediction.
        raw = b'{"custom_worker_field": [1, 2, 3], "unit": "MWh", "nested": {"x": true}}'
        temporary = ticket_dir / "response.json.tmp"
        temporary.write_bytes(raw)
        assert client.get(f"/api/tickets/{ticket_id}").status_code == 202
        os.replace(temporary, ticket_dir / "response.json")
        result = client.get(f"/api/tickets/{ticket_id}")
        assert result.status_code == 200
        assert result.content == raw
    with TestClient(create_app(settings, datasets=repository, weather=FakeWeather())) as client:
        assert client.get(f"/api/tickets/{ticket_id}").content == raw
        assert client.get("/api/tickets/not-a-ticket").status_code == 404


def test_worker_timeout_and_invalid_json_are_reported(tmp_path):
    settings = settings_for(tmp_path, ticket_timeout_seconds=1)
    app = create_app(settings, datasets=MemoryDatasets({}), weather=FakeWeather())
    with TestClient(app) as client:
        ticket_id = client.post("/api/tickets", json={"turbine_id": "A", "horizon_start": "2026-02-05", "history_days": 1}).json()["ticket_id"]
        path = settings.tickets_dir / ticket_id
        wait_for_input(client, ticket_id, path)
        app.state.tickets.jobs[ticket_id].created_at -= timedelta(seconds=10)
        assert client.get(f"/api/tickets/{ticket_id}").status_code == 504
        (path / "response.json").write_text('{"value": NaN}', encoding="utf-8")
        result = client.get(f"/api/tickets/{ticket_id}")
        assert result.status_code == 502
        assert result.json()["error"]["code"] == "invalid_ml_response"


def test_cleanup_only_removes_expired_generated_ticket_directories(tmp_path):
    settings = settings_for(tmp_path, result_ttl_seconds=1)
    app = create_app(settings, datasets=MemoryDatasets({}), weather=FakeWeather())
    with TestClient(app) as client:
        ticket_id = client.post("/api/tickets", json={"turbine_id": "A", "horizon_start": "2026-02-05", "history_days": 1}).json()["ticket_id"]
        path = settings.tickets_dir / ticket_id
        wait_for_input(client, ticket_id, path)
        result = path / "response.json"
        result.write_text('{"ok":true}', encoding="utf-8")
        os.utime(result, (time.time() - 20, time.time() - 20))
        keep = settings.tickets_dir / "do-not-delete"
        keep.mkdir()
        app.state.tickets.cleanup()
        assert not path.exists()
        assert keep.exists()
