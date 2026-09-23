"""
This indirection exists so the CV contract can change without breaking the
frontend: api/routes.py always goes through to_ticket_out rather than handing
an AnalyzeResponse straight to the client.
"""

from api.schemas import DetectionOut, TicketOut
from shared.cv_contract import AnalyzeResponse

_STATUS_MAP = {
    "ok": "done",
    "error": "error",
}


def to_ticket_out(ticket_id: str, resp: AnalyzeResponse) -> TicketOut:
    status = _STATUS_MAP[resp.status]
    output_url = f"/files/{ticket_id}/output.jpg" if resp.status == "ok" else None
    return TicketOut(
        ticket_id=ticket_id,
        status=status,
        detections=[
            DetectionOut(label=d.label, confidence=d.confidence, box=list(d.box))
            for d in resp.detections
        ],
        output_url=output_url,
        error=resp.error,
    )
