from datetime import datetime
from pathlib import Path
import csv
import time

import pytest

from fastapi.testclient import TestClient

from back.config import Settings
from back.dataset import DatasetSeries, WeatherValue
from back.main import create_app
from back.schemas import UTC


@pytest.mark.parametrize("sampling_step", [3, 6])
def test_bootstrap_defaults_can_be_posted_directly_and_horizon_is_fixed(tmp_path, sampling_step):
    class Datasets:
        def get(self, turbine):
            return DatasetSeries({datetime(2026, 1, 31, 23, 50, tzinfo=UTC): WeatherValue(5, 2, "dataset")})

    class Weather:
        async def weather_for(self, turbine, timestamps, **kwargs):
            return {t: WeatherValue(6, 3, "fixture") for t in timestamps}

    settings = Settings(tickets_dir=tmp_path / "tickets", cache_dir=tmp_path / "cache", web_dist=tmp_path / "no-web", turbine_timezone="UTC", sampling_step=sampling_step, inference_enabled=False)
    with TestClient(create_app(settings, datasets=Datasets(), weather=Weather())) as client:
        response = client.get("/api/bootstrap")
        assert response.status_code == 200
        data = response.json()
        assert data["prediction_hours"] == 48
        assert len(data["turbines"]) == 2
        assert data["defaults"]["horizon_start"] == "2026-02-01T00:00:00+00:00"
        assert set(data["defaults"]) == {"turbine_id", "horizon_start", "history_days"}
        assert "step_options" not in data["limits"]
        submitted = client.post("/api/tickets", json=data["defaults"])
        assert submitted.status_code == 202
        assert submitted.json()["input"]["prediction_hours"] == 48
        assert "step" not in submitted.json()["input"]
        data_file = settings.tickets_dir / submitted.json()["ticket_id"] / "data.csv"
        for _ in range(200):
            if data_file.exists():
                break
            time.sleep(0.01)
        with data_file.open() as handle:
            rows = list(csv.DictReader(handle))
        assert sum(row["phase"] == "forecast" for row in rows) == 48 * sampling_step
        assert client.post("/api/tickets", json={**data["defaults"], "step": 6}).status_code == 422
        assert client.post("/api/tickets", json={**data["defaults"], "horizon_hours": 24}).status_code == 422
