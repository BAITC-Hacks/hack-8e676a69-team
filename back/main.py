from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from back.config import Settings, TURBINES
from back.dataset import DatasetRepository, PreparationError
from back.inputs import InputBuilder
from back.schemas import TicketRequest
from back.tickets import TicketStore
from back.weather import OpenMeteo


def create_app(settings: Settings | None = None, *, datasets=None, weather=None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    repository = datasets or DatasetRepository(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(follow_redirects=False, headers={"User-Agent": "HackAlem-Wind-Backend/1.0"}) as client:
            provider = weather or OpenMeteo(settings, client)
            app.state.tickets = TicketStore(settings, InputBuilder(settings, repository, provider))
            cleanup = asyncio.create_task(app.state.tickets.cleanup_loop())
            try:
                yield
            finally:
                cleanup.cancel()
                await asyncio.gather(cleanup, return_exceptions=True)
                await app.state.tickets.close()

    app = FastAPI(
        title="HackAlem wind forecast backend",
        description="Weather-only data.csv tickets; the ML worker supplies response.json. Dates without offsets use the configured turbine timezone.",
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"], allow_headers=["Content-Type"], allow_credentials=False)

    @app.exception_handler(PreparationError)
    async def preparation_error(request: Request, exc: PreparationError):
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": str(exc)}}, headers={"Cache-Control": "no-store"})

    @app.get("/health")
    async def health():
        return {"ok": True, "service": "wind-backend", "timezone": settings.turbine_timezone}

    async def turbine_catalog():
        output = []
        for turbine in TURBINES.values():
            series = await asyncio.to_thread(repository.get, turbine)
            output.append({
                "id": turbine.id,
                "name": f"Turbine {turbine.id}",
                "dataset_number": turbine.number,
                "latitude": turbine.latitude,
                "longitude": turbine.longitude,
                "dataset_start": series.times[0].astimezone(settings.timezone).isoformat(),
                "dataset_end": series.times[-1].astimezone(settings.timezone).isoformat(),
                "timezone": settings.turbine_timezone,
                "default_horizon_start": datetime.combine(series.times[-1].astimezone(settings.timezone).date() + timedelta(days=1), time.min, tzinfo=settings.timezone).isoformat(),
            })
        return output

    @app.get("/api/bootstrap")
    async def bootstrap():
        catalog = await turbine_catalog()
        return {
            "prediction_hours": 48,
            "timezone": settings.turbine_timezone,
            "turbines": catalog,
            "defaults": {
                "turbine_id": catalog[0]["id"],
                "horizon_start": catalog[0]["default_horizon_start"],
                "history_days": 30,
            },
            "limits": {
                "history_days": {"min": 1, "max": 90},
            },
            "poll_interval_ms": 1000,
        }

    @app.get("/api/turbines")
    async def turbines():
        return await turbine_catalog()

    @app.post("/api/tickets", status_code=202)
    async def create_ticket(body: TicketRequest, request: Request):
        return request.app.state.tickets.create(body)

    @app.get("/api/tickets/{ticket_id}")
    async def get_ticket(ticket_id: str, request: Request):
        status, content = await asyncio.to_thread(request.app.state.tickets.poll, ticket_id)
        if status == 200:
            return Response(content=content, media_type="application/json", headers={"Cache-Control": "no-store"})
        return JSONResponse(status_code=status, content=content, headers={"Retry-After": "1", "Cache-Control": "no-store"})

    if settings.web_dist.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")
    else:
        @app.get("/")
        async def index():
            return {"service": "wind-backend", "docs": "/docs"}

    return app


app = create_app()
