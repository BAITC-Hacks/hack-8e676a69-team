"""
Frontend-facing models, deliberately separate from shared/cv_contract.py -
the frontend should never depend on the shape the cv process happens to
return.
"""

from typing import Literal

from pydantic import BaseModel


class DetectionOut(BaseModel):
    label: str
    confidence: float
    box: list[float]


class TicketOut(BaseModel):
    ticket_id: str
    status: Literal["pending", "running", "done", "error"]
    detections: list[DetectionOut] = []
    output_url: str | None = None
    error: str | None = None
