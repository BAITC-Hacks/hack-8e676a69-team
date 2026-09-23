from datetime import datetime

from fastapi.testclient import TestClient

from back.config import Settings
from back.dataset import DatasetSeries, WeatherValue
from back.main import create_app
from back.schemas import UTC


def test_bootstrap_defaults_can_be_posted_directly_and_horizon_is_fixed(tmp_path):
    class Datasets:
        def get(self, turbine):
            return DatasetSeries({datetime(2026, 1, 31, 23, 50, tzinfo=UTC): WeatherValue(5, 2, "dataset")})

    class Weather:
        async def weather_for(self, turbine, timestamps, **kwargs):
            return {t: WeatherValue(6, 3, "fixture") for t in timestamps}

    settings = Settings(tickets_dir=tmp_path / "tickets", cache_dir=tmp_path / "cache", web_dist=tmp_path / "no-web", turbine_timezone="UTC")
    with TestClient(create_app(settings, datasets=Datasets(), weather=Weather())) as client:
        response = client.get("/api/bootstrap")
        assert response.status_code == 200
        data = response.json()
        assert data["prediction_hours"] == 48
        assert len(data["turbines"]) == 2
        assert data["defaults"]["horizon_start"] == "2026-02-01T00:00:00+00:00"
        assert {"step": 6, "interval_minutes": 10} in data["limits"]["step_options"]
        submitted = client.post("/api/tickets", json=data["defaults"])
        assert submitted.status_code == 202
        assert submitted.json()["input"]["forecast_rows"] == 288
        assert submitted.json()["input"]["prediction_hours"] == 48
        assert client.post("/api/tickets", json={**data["defaults"], "horizon_hours": 24}).status_code == 422
