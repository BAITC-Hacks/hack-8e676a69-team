from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

UTC = timezone.utc


class TicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "example": {"turbine_id": "A", "horizon_start": "2026-02-05", "history_days": 30}
    })

    turbine_id: Literal["A", "B"]
    horizon_start: datetime = Field(description="Date or ISO datetime. Naive values use TURBINE_TIMEZONE.")
    history_days: int = Field(default=30, ge=1, le=90)

    @property
    def horizon_hours(self) -> int:
        """Model horizon is fixed. The frontend selects its display window."""
        return 48

    @field_validator("turbine_id", mode="before")
    @classmethod
    def normalize_turbine(cls, value):
        key = str(value).strip().upper()
        return {"1": "A", "2": "B"}.get(key, key)

    @field_validator("horizon_start", mode="before")
    @classmethod
    def parse_date(cls, value):
        if isinstance(value, str) and len(value) == 10:
            return datetime.combine(date.fromisoformat(value), time.min)
        if isinstance(value, date) and not isinstance(value, datetime):
            return datetime.combine(value, time.min)
        return value

    @model_validator(mode="after")
    def aligned_start(self):
        dt = self.horizon_start
        if dt.minute or dt.second or dt.microsecond:
            raise ValueError("horizon_start must be a date or a whole-hour timestamp")
        return self

    def start_utc(self, site_timezone: ZoneInfo) -> datetime:
        value = self.horizon_start
        if value.tzinfo is None:
            value = value.replace(tzinfo=site_timezone)
        return value.astimezone(UTC)

    def timestamps(self, site_timezone: ZoneInfo, sampling_step: int) -> list[datetime]:
        start = self.start_utc(site_timezone) - timedelta(days=self.history_days)
        count = (self.history_days * 24 + self.horizon_hours) * sampling_step
        return [start + timedelta(minutes=(60 // sampling_step) * i) for i in range(count)]
