from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_ROOT.parent


@dataclass(frozen=True)
class Turbine:
    id: str
    number: int
    latitude: float
    longitude: float


TURBINES = {
    "A": Turbine("A", 1, 43.645150, 78.535604),
    "B": Turbine("B", 2, 43.643198, 78.538828),
}


def default_datasets_dir() -> Path:
    return BACKEND_ROOT / "data"


def env_path(name: str, default: Path) -> Path:
    path = Path(os.getenv(name) or default).expanduser()
    return (path if path.is_absolute() else BACKEND_ROOT / path).resolve()


@dataclass(frozen=True)
class Settings:
    tickets_dir: Path = PROJECT_ROOT / "tickets"
    datasets_dir: Path = field(default_factory=default_datasets_dir)
    cache_dir: Path = BACKEND_ROOT / ".cache" / "weather"
    web_dist: Path = PROJECT_ROOT / "frontend" / "dist"
    # Location-based default, NOT a confirmed statement about the source CSV.
    turbine_timezone: str = "Asia/Almaty"
    weather_model: str = "gfs_global"
    wind_variable: str = "wind_speed_100m"
    weather_timeout_seconds: float = 25.0
    # Conservative policy assumption, not per-run publication metadata.
    forecast_availability_margin_hours: int = 12
    ticket_timeout_seconds: int = 1800
    result_ttl_seconds: int = 1800
    max_active_tickets: int = 32
    use_dataset_for_horizon: bool = True
    use_historical_weather: bool = True
    sampling_step: int = 6
    inference_enabled: bool = True
    inference_model_dir: Path = PROJECT_ROOT / 'inference' / 'models'
    inference_workers: int = 2
    inference_threads: int = 1
    cors_origins: tuple[str, ...] = ("*",)

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.turbine_timezone)

    @property
    def interval_minutes(self) -> int:
        return 60 // self.sampling_step

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            tickets_dir=env_path("TICKETS_DIR", defaults.tickets_dir),
            datasets_dir=env_path("DATASETS_DIR", defaults.datasets_dir),
            cache_dir=env_path("WEATHER_CACHE_DIR", defaults.cache_dir),
            web_dist=env_path("WEB_DIST", defaults.web_dist),
            turbine_timezone=os.getenv("TURBINE_TIMEZONE", defaults.turbine_timezone),
            weather_model=os.getenv("WEATHER_MODEL", defaults.weather_model),
            wind_variable=os.getenv("WEATHER_WIND_VARIABLE", defaults.wind_variable),
            weather_timeout_seconds=float(os.getenv("WEATHER_TIMEOUT_SECONDS", "25")),
            forecast_availability_margin_hours=int(os.getenv("FORECAST_AVAILABILITY_MARGIN_HOURS", "12")),
            ticket_timeout_seconds=int(os.getenv("TICKET_TIMEOUT_SECONDS", "1800")),
            result_ttl_seconds=int(os.getenv("RESULT_TTL_SECONDS", "1800")),
            max_active_tickets=int(os.getenv("MAX_ACTIVE_TICKETS", "32")),
            use_dataset_for_horizon=os.getenv("USE_DATASET_FOR_HORIZON", "true").lower() in {"1", "true", "yes"},
            use_historical_weather=os.getenv("USE_HISTORICAL_WEATHER", "true").lower() in {"1", "true", "yes"},
            sampling_step=int(os.getenv("ML_STEP", "6")),
            inference_enabled=os.getenv('INFERENCE_ENABLED', 'true').lower() in {'1', 'true', 'yes'},
            inference_model_dir=env_path('INFERENCE_MODEL_DIR', defaults.inference_model_dir),
            inference_workers=int(os.getenv('INFERENCE_WORKERS', '2')),
            inference_threads=int(os.getenv('INFERENCE_THREADS', '1')),
            cors_origins=tuple(x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()),
        )

    def validate(self) -> None:
        self.timezone
        if self.inference_workers < 1 or self.inference_threads < 1:
            raise ValueError('Inference worker/thread counts must be positive')
        if not 1 <= self.sampling_step <= 60 or 60 % self.sampling_step:
            raise ValueError("ML_STEP must be a positive divisor of 60; 6 means one row every 10 minutes")
        if not 1 <= self.forecast_availability_margin_hours <= 24:
            raise ValueError("FORECAST_AVAILABILITY_MARGIN_HOURS must be between 1 and 24")
        if min(self.weather_timeout_seconds, self.ticket_timeout_seconds, self.result_ttl_seconds, self.max_active_tickets) <= 0:
            raise ValueError("Timeouts, retention, and ticket capacity must be positive")
        if self.wind_variable not in {"wind_speed_10m", "wind_speed_80m", "wind_speed_100m", "wind_speed_120m", "wind_speed_180m"}:
            raise ValueError("Unsupported WEATHER_WIND_VARIABLE")
