from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
    local = PROJECT_ROOT.parent / "tracks" / "Энергетика"
    return local if local.is_dir() else Path("/data/datasets")


@dataclass(frozen=True)
class Settings:
    tickets_dir: Path = PROJECT_ROOT / "tickets"
    datasets_dir: Path = field(default_factory=default_datasets_dir)
    cache_dir: Path = PROJECT_ROOT / ".cache" / "weather"
    web_dist: Path = PROJECT_ROOT / "web" / "dist"
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
    cors_origins: tuple[str, ...] = ("*",)

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.turbine_timezone)

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            tickets_dir=Path(os.getenv("TICKETS_DIR", str(defaults.tickets_dir))).resolve(),
            datasets_dir=Path(os.getenv("DATASETS_DIR", str(defaults.datasets_dir))).resolve(),
            cache_dir=Path(os.getenv("WEATHER_CACHE_DIR", str(defaults.cache_dir))).resolve(),
            web_dist=Path(os.getenv("WEB_DIST", str(defaults.web_dist))).resolve(),
            turbine_timezone=os.getenv("TURBINE_TIMEZONE", defaults.turbine_timezone),
            weather_model=os.getenv("WEATHER_MODEL", defaults.weather_model),
            wind_variable=os.getenv("WEATHER_WIND_VARIABLE", defaults.wind_variable),
            weather_timeout_seconds=float(os.getenv("WEATHER_TIMEOUT_SECONDS", "25")),
            forecast_availability_margin_hours=int(os.getenv("FORECAST_AVAILABILITY_MARGIN_HOURS", "12")),
            ticket_timeout_seconds=int(os.getenv("TICKET_TIMEOUT_SECONDS", "1800")),
            result_ttl_seconds=int(os.getenv("RESULT_TTL_SECONDS", "1800")),
            max_active_tickets=int(os.getenv("MAX_ACTIVE_TICKETS", "32")),
            use_dataset_for_horizon=os.getenv("USE_DATASET_FOR_HORIZON", "true").lower() in {"1", "true", "yes"},
            cors_origins=tuple(x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()),
        )

    def validate(self) -> None:
        self.timezone
        if not 1 <= self.forecast_availability_margin_hours <= 24:
            raise ValueError("FORECAST_AVAILABILITY_MARGIN_HOURS must be between 1 and 24")
        if min(self.weather_timeout_seconds, self.ticket_timeout_seconds, self.result_ttl_seconds, self.max_active_tickets) <= 0:
            raise ValueError("Timeouts, retention, and ticket capacity must be positive")
        if self.wind_variable not in {"wind_speed_10m", "wind_speed_80m", "wind_speed_100m", "wind_speed_120m", "wind_speed_180m"}:
            raise ValueError("Unsupported WEATHER_WIND_VARIABLE")
