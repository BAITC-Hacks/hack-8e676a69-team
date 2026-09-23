from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from back.config import Settings
from back.dataset import PreparationError
from back.inputs import InputBuilder, publish_csv
from back.schemas import TicketRequest, UTC

logger = logging.getLogger(__name__)
TICKET_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass
class Job:
    created_at: datetime
    error: PreparationError | None = None


class TicketStore:
    def __init__(self, settings: Settings, builder: InputBuilder):
        self.settings = settings
        self.builder = builder
        self.root = settings.tickets_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.preparation_slots = asyncio.Semaphore(4)

    def directory(self, ticket_id: str) -> Path:
        if not TICKET_ID.fullmatch(ticket_id):
            raise PreparationError("Ticket not found.", "ticket_not_found", 404)
        path = self.root / ticket_id
        if path.is_symlink() or path.resolve().parent != self.root or not path.is_dir():
            raise PreparationError("Ticket not found or expired.", "ticket_not_found", 404)
        return path

    def _directories(self):
        for path in self.root.iterdir():
            if TICKET_ID.fullmatch(path.name) and path.is_dir() and not path.is_symlink() and path.resolve().parent == self.root:
                yield path

    def _created(self, path: Path) -> datetime:
        if path.name in self.jobs:
            return self.jobs[path.name].created_at
        data = path / "data.csv"
        timestamp = (data if data.exists() else path).stat().st_mtime
        return datetime.fromtimestamp(timestamp, UTC)

    def active_count(self) -> int:
        now = datetime.now(UTC)
        return sum(
            1 for path in self._directories()
            if not (path / "response.json").exists()
            and not (self.jobs.get(path.name) and self.jobs[path.name].error)
            and (now - self._created(path)).total_seconds() < self.settings.ticket_timeout_seconds
        )

    def create(self, request: TicketRequest) -> dict:
        if self.active_count() >= self.settings.max_active_tickets:
            raise PreparationError("Too many active tickets. Wait for a result before submitting another.", "ticket_capacity", 429)
        ticket_id = uuid.uuid4().hex
        path = self.root / ticket_id
        path.mkdir()
        now = datetime.now(UTC)
        self.jobs[ticket_id] = Job(now)
        task = asyncio.create_task(self._prepare(ticket_id, request, now), name=f"prepare-{ticket_id}")
        self.tasks[ticket_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(ticket_id, None))
        start = request.start_utc(self.settings.timezone)
        return {
            "ticket_id": ticket_id,
            "status": "preparing",
            "poll_url": f"/api/tickets/{ticket_id}",
            "input": {
                "turbine_id": request.turbine_id,
                "history_start": (start - timedelta(days=request.history_days)).astimezone(self.settings.timezone).isoformat(),
                "horizon_start": start.astimezone(self.settings.timezone).isoformat(),
                "horizon_end_exclusive": (start + timedelta(hours=request.horizon_hours)).astimezone(self.settings.timezone).isoformat(),
                "step": request.step,
                "interval_minutes": request.interval_minutes,
                "history_rows": request.history_days * 24 * request.step,
                "forecast_rows": request.horizon_hours * request.step,
                "timezone": self.settings.turbine_timezone,
                "prediction_hours": 48,
                "use_dataset_for_horizon": self.settings.use_dataset_for_horizon,
            },
        }

    async def _prepare(self, ticket_id: str, request: TicketRequest, now: datetime):
        try:
            async with self.preparation_slots:
                rows = await self.builder.build(request, now=now)
                await asyncio.to_thread(publish_csv, self.directory(ticket_id), rows)
        except asyncio.CancelledError:
            raise
        except PreparationError as exc:
            self.jobs[ticket_id].error = exc
            logger.warning("Ticket %s: %s", ticket_id, exc)
        except Exception:
            logger.exception("Failed to prepare ticket %s", ticket_id)
            self.jobs[ticket_id].error = PreparationError("Failed to prepare ML input. Check backend logs.", "preparation_failed", 500)

    def poll(self, ticket_id: str) -> tuple[int, dict | bytes]:
        path = self.directory(ticket_id)
        response = path / "response.json"
        if response.is_file():
            if response.is_symlink():
                raise PreparationError("ML response must be a regular file.", "invalid_ml_response", 502)
            raw = response.read_bytes()
            try:
                def reject_constant(value):
                    raise ValueError(f"Non-JSON constant: {value}")
                json.loads(raw, parse_constant=reject_constant)
            except (ValueError, UnicodeError) as exc:
                raise PreparationError("ML response.json is not valid JSON. The worker must publish it atomically.", "invalid_ml_response", 502) from exc
            return 200, raw
        job = self.jobs.get(ticket_id)
        if job and job.error:
            raise job.error
        if (datetime.now(UTC) - self._created(path)).total_seconds() > self.settings.ticket_timeout_seconds:
            raise PreparationError("The ML worker did not publish response.json before the ticket timeout.", "ml_timeout", 504)
        if (path / "data.csv").is_file():
            state = "pending"
        elif ticket_id in self.tasks:
            state = "preparing"
        else:
            raise PreparationError("Input preparation was interrupted. Submit a new ticket.", "preparation_interrupted", 503)
        return 202, {"ticket_id": ticket_id, "status": state, "poll_after_ms": 1000}

    def cleanup(self) -> None:
        now = datetime.now(UTC)
        for path in list(self._directories()):
            if path.name in self.tasks:
                continue
            response = path / "response.json"
            if response.is_file():
                age = now.timestamp() - response.stat().st_mtime
                expired = age > self.settings.result_ttl_seconds
            else:
                expired = (now - self._created(path)).total_seconds() > self.settings.ticket_timeout_seconds + self.settings.result_ttl_seconds
            if expired:
                # Recheck the absolute target immediately before recursive removal.
                target = path.resolve()
                if path.is_symlink() or target.parent != self.root or not TICKET_ID.fullmatch(target.name):
                    continue
                try:
                    shutil.rmtree(target)
                except OSError:
                    logger.warning("Could not clean expired ticket %s", path.name, exc_info=True)
                    continue
                self.jobs.pop(path.name, None)

    async def cleanup_loop(self):
        while True:
            await asyncio.sleep(15)
            self.cleanup()

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
