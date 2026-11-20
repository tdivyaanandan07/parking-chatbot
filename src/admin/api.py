from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src import graph
from src.db import requests_db
from src.admin.recording import record_approved

app = FastAPI(title="Admin Inbox")


class NewRequest(BaseModel):
    reservation: dict = {}
    message: str = ""
    thread_id: Optional[str] = None


class Decision(BaseModel):
    approved: bool


class Lookup(BaseModel):
    reference: str
    car_number: str


def _public(req: dict) -> dict:
    """Shape a stored row the way the admin UI expects it."""
    return {
        "id": req["reference"],
        "reference": req["reference"],
        "details": {
            "reservation": {k: req[k] for k in ("name", "surname", "car_number", "period")},
            "message": req["message"],
        },
        "status": req["status"],
        "note": req["note"],
        "created_at": req["created_at"],
        "decided_at": req["decided_at"],
    }


@app.post("/requests")
def create_request(payload: NewRequest):
    return _public(requests_db.create_request(payload.reservation, payload.message,
                                              payload.thread_id))


@app.get("/requests/pending")
def pending():
    return [_public(r) for r in requests_db.pending_requests()]


@app.post("/requests/lookup")
def lookup(q: Lookup):
    """Customer status check: needs the reference AND the car number (POST keeps them out of URLs)."""
    req = requests_db.lookup(q.reference, q.car_number)
    if not req:
        raise HTTPException(404, "No reservation matches that reference and car number")
    return _public(req)


@app.post("/requests/{rid}/decision")
def decide(rid: str, d: Decision):
    req = requests_db.get_request(rid)
    if not req:
        raise HTTPException(404, "Not found")
    if req["status"] != "pending":
        raise HTTPException(409, f"Already decided: {req['status']}")

    # Normal path: resume the graph run paused at admin_approval; its record
    # node writes an approved booking through MCP and updates the status.
    if req["thread_id"] and graph.resume_with_decision(req["thread_id"], d.approved):
        return _public(requests_db.get_request(rid))

    # No paused run (request posted straight to the API): apply the same steps here.
    if not d.approved:
        return _public(requests_db.set_status(rid, "refused"))
    return _public(record_approved(rid))
