import os

# Must be set BEFORE any ml import (torch, ultralytics, etc pick this up at
# import time). Otherwise torch grabs all 4 cores on this box and starves the
# api process and Caddy of CPU.
os.environ.setdefault("OMP_NUM_THREADS", "3")

import shutil
import threading
import time
from pathlib import Path

from fastapi import FastAPI

from shared.cv_contract import AnalyzeRequest, AnalyzeResponse, Detection

app = FastAPI(title="hackalem-cv")

model = None
# One inference at a time; this box has 4 cores and models are not reliably
# thread-safe, so we serialize access instead of risking concurrent calls
# into the same model object.
_lock = threading.Semaphore(1)


@app.on_event("startup")
def load() -> None:
    global model
    # STUB: replace with real model loading. Load ONCE at startup, never per
    # request - a real model load is far too slow to do inside a handler.
    #
    # from ultralytics import YOLO
    # model = YOLO("/data/models/yolov8n.pt")
    model = "STUB"


@app.get("/health")
def health() -> dict:
    return {"ok": model is not None}


# Plain `def`, NOT `async def`: FastAPI runs sync handlers in a threadpool,
# so this CPU-bound work does not block the event loop the way an
# `async def` doing blocking work would.
@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    start = time.monotonic()
    try:
        ticket_dir = Path(req.ticket_dir)
        input_path = ticket_dir / "input.jpg"
        if not input_path.exists():
            raise ValueError(f"input.jpg not found in {ticket_dir}")

        with _lock:
            # STUB: real inference goes here, e.g.
            #   results = model(str(input_path))
            #   detections = [Detection(...) for r in results ...]
            detections = [Detection(label="STUB", confidence=0.99, box=(10, 10, 200, 200))]

            output_path = ticket_dir / "output.jpg"
            shutil.copy(input_path, output_path)

        took_ms = int((time.monotonic() - start) * 1000)
        return AnalyzeResponse(
            ticket_id=req.ticket_id,
            status="ok",
            detections=detections,
            took_ms=took_ms,
        )
    except Exception as e:
        # Never raise - always return the contract, so the api process gets a
        # well-formed AnalyzeResponse even when something goes wrong here.
        took_ms = int((time.monotonic() - start) * 1000)
        return AnalyzeResponse(
            ticket_id=req.ticket_id,
            status="error",
            error=str(e),
            took_ms=took_ms,
        )
