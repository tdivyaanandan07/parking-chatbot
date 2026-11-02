import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Admin Inbox")
REQUESTS: dict[str, dict] = {}


class Decision(BaseModel):
    approved: bool


@app.post("/requests")
def create_request(payload: dict):
    rid = str(uuid.uuid4())
    REQUESTS[rid] = {"id": rid, "details": payload, "status": "pending"}
    return REQUESTS[rid]


@app.get("/requests/pending")
def pending():
    return [r for r in REQUESTS.values() if r["status"] == "pending"]


@app.get("/requests/{rid}")
def get_request(rid: str):
    if rid not in REQUESTS:
        raise HTTPException(404, "Not found")
    return REQUESTS[rid]


@app.post("/requests/{rid}/decision")
def decide(rid: str, d: Decision):
    if rid not in REQUESTS:
        raise HTTPException(404, "Not found")
    REQUESTS[rid]["status"] = "approved" if d.approved else "refused"
    return REQUESTS[rid]