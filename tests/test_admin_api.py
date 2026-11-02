from fastapi.testclient import TestClient
from src.admin.api import app

client = TestClient(app)


def test_create_and_pending():
    rid = client.post("/requests", json={"x": 1}).json()["id"]
    assert rid in [r["id"] for r in client.get("/requests/pending").json()]


def test_decision():
    rid = client.post("/requests", json={"x": 1}).json()["id"]
    res = client.post(f"/requests/{rid}/decision", json={"approved": True}).json()
    assert res["status"] == "approved"