import pytest
from fastapi.testclient import TestClient
from src.admin import api
from src.db import requests_db

client = TestClient(api.app)
RES = {"name": "Ann", "surname": "Lee", "car_number": "AB-1234",
       "period": "2099-11-05 09:00 to 18:00"}


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(requests_db, "DB_PATH", tmp_path / "test.db")
    saved = []
    monkeypatch.setattr(api, "save_via_mcp", lambda *a: saved.append(a) or "OK: saved")
    return saved


def _create():
    return client.post("/requests", json={"reservation": RES, "message": "hi"}).json()


def test_create_returns_reference_and_is_pending():
    r = _create()
    assert r["reference"].startswith("CP-") and r["status"] == "pending"
    assert r["id"] in [p["id"] for p in client.get("/requests/pending").json()]


def test_references_are_unique():
    assert len({_create()["reference"] for _ in range(20)}) == 20


def test_approve_saves_via_mcp_with_reference(temp_db):
    rid = _create()["id"]
    res = client.post(f"/requests/{rid}/decision", json={"approved": True}).json()
    assert res["status"] == "approved"
    assert temp_db == [("Ann Lee", "AB-1234", "2099-11-05 09:00 to 18:00", rid)]
    assert rid not in [p["id"] for p in client.get("/requests/pending").json()]


def test_refuse_does_not_save(temp_db):
    rid = _create()["id"]
    assert client.post(f"/requests/{rid}/decision", json={"approved": False}).json()["status"] == "refused"
    assert temp_db == []


def test_failed_save_is_reported(monkeypatch):
    monkeypatch.setattr(api, "save_via_mcp", lambda *a: "ERROR: overlapping booking exists")
    rid = _create()["id"]
    res = client.post(f"/requests/{rid}/decision", json={"approved": True}).json()
    assert res["status"] == "save_failed" and "overlapping" in res["note"]


def test_cannot_decide_twice():
    rid = _create()["id"]
    client.post(f"/requests/{rid}/decision", json={"approved": False})
    assert client.post(f"/requests/{rid}/decision", json={"approved": True}).status_code == 409


def test_lookup_needs_matching_car():
    ref = _create()["reference"]
    ok = client.post("/requests/lookup", json={"reference": ref.lower(), "car_number": "ab 1234"})
    assert ok.status_code == 200 and ok.json()["status"] == "pending"
    wrong_car = client.post("/requests/lookup", json={"reference": ref, "car_number": "ZZ-9999"})
    wrong_ref = client.post("/requests/lookup", json={"reference": "CP-AAAAAA", "car_number": "AB-1234"})
    assert wrong_car.status_code == wrong_ref.status_code == 404
    assert wrong_car.json() == wrong_ref.json()  # no hint about which part was wrong
