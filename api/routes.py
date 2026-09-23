# STUB-FIRST: these endpoints return real HTTP shapes before the real logic exists,
# so the frontend can be built against them from minute 20. Replace bodies, keep shapes.

import uuid

import aiofiles
import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile

from api import db
from api.config import CV_TIMEOUT, CV_URL, DATA_DIR
from api.mappers import to_ticket_out
from api.schemas import TicketOut
from shared.cv_contract import AnalyzeRequest, AnalyzeResponse

router = APIRouter()


def _row_to_ticket_out(row: dict) -> TicketOut:
    if row["result"]:
        return TicketOut.model_validate_json(row["result"])
    return TicketOut(ticket_id=row["id"], status=row["status"], detections=[])


@router.post("/tickets", response_model=TicketOut)
async def create_ticket(file: UploadFile = File(...)) -> TicketOut:
    tid = uuid.uuid4().hex
    d = DATA_DIR / tid
    d.mkdir(parents=True, exist_ok=True)

    input_path = d / "input.jpg"
    async with aiofiles.open(input_path, "wb") as out:
        await out.write(await file.read())

    db.insert_ticket(tid, "pending")
    db.update_ticket(tid, "running")

    req = AnalyzeRequest(ticket_id=tid, ticket_dir=str(d.resolve()), mode="detect")

    try:
        async with httpx.AsyncClient(timeout=CV_TIMEOUT) as client:
            r = await client.post(CV_URL, json=req.model_dump(mode="json"))
    except httpx.TimeoutException:
        db.update_ticket(tid, "error")
        raise HTTPException(504, "cv timeout")
    except httpx.HTTPError:
        db.update_ticket(tid, "error")
        raise HTTPException(502, "cv service unavailable")

    resp = AnalyzeResponse.model_validate_json(r.text)
    out = to_ticket_out(tid, resp)
    db.update_ticket(tid, out.status, out.model_dump_json())
    return out


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
async def get_ticket(ticket_id: str) -> TicketOut:
    row = db.get_ticket(ticket_id)
    if row is None:
        raise HTTPException(404, "ticket not found")
    return _row_to_ticket_out(row)


@router.get("/tickets", response_model=list[TicketOut])
async def list_tickets() -> list[TicketOut]:
    rows = db.list_tickets()
    return [_row_to_ticket_out(row) for row in rows]
