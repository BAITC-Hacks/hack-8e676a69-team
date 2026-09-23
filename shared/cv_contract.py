"""
Shared pydantic v2 models used by BOTH the api process and the cv process.

The transport between the two processes is swappable: today it is a plain
HTTP POST (api -> cv), but nothing here assumes that. If HTTP ever becomes a
problem (e.g. the cv process needs to run on a different box, or we want to
decouple the two lifecycles) this same contract could be carried over a
folder-polling transport instead, with no changes to the shape of the data.

Payload files (e.g. input.jpg, output.jpg) live in the ticket dir on shared
disk and are referenced by path, never embedded in the request/response body.
When writing anything into a ticket dir: ALWAYS write the payload file(s)
first, and write/rename the signal file last, atomically. That ordering is
what lets a reader safely poll for the signal file without ever observing a
half-written payload.
"""

from typing import Literal

from pydantic import BaseModel

# NOTE: these field names are placeholders, rewrite once the hackathon task is known.


class Detection(BaseModel):
    label: str
    confidence: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2


class AnalyzeRequest(BaseModel):
    ticket_id: str
    ticket_dir: str  # absolute path; contains input.jpg
    mode: Literal["detect", "classify"] = "detect"


class AnalyzeResponse(BaseModel):
    ticket_id: str
    status: Literal["ok", "error"]
    detections: list[Detection] = []
    error: str | None = None
    took_ms: int = 0
