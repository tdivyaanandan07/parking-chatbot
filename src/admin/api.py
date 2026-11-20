from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.db import requests_db
from src.mcp_client import save_via_mcp

app = FastAPI(title="Admin Inbox")


class NewRequest(BaseModel):
    reservation: dict = {}
    message: str = ""


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
    return _public(requests_db.create_request(payload.reservation, payload.message))


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
    if not d.approved:
        return _public(requests_db.set_status(rid, "refused"))

    # Approved: write it to the reservations file through the MCP server now,
    # since the customer is no longer waiting in the chat for the outcome.
    try:
        result = save_via_mcp(f"{req['name']} {req['surname']}", req["car_number"],
                              req["period"], rid)
    except Exception as e:
        result = f"ERROR: {e}"
    if "OK" in result:
        return _public(requests_db.set_status(rid, "approved"))
    return _public(requests_db.set_status(rid, "save_failed", result))
