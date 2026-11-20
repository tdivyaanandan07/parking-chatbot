import pytest
from src.db import requests_db
from src.db.requests_db import parse_reference, new_reference


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(requests_db, "DB_PATH", tmp_path / "test.db")


def test_reference_format():
    ref = new_reference()
    assert len(ref) == 9 and parse_reference(ref) == ref
    assert not set(ref[3:]) & set("01OI")


def test_parse_reference_from_text():
    assert parse_reference("what's the status of cp-7k3f9q please") == "CP-7K3F9Q"
    assert parse_reference("ref CP7K3F9Q") == "CP-7K3F9Q"
    assert parse_reference("my car is AB-1234") is None


def test_persists_and_updates_status():
    ref = requests_db.create_request({"car_number": "AB-1234"}, "msg")["reference"]
    assert requests_db.get_request(ref)["status"] == "pending"
    requests_db.set_status(ref, "refused")
    assert requests_db.get_request(ref)["status"] == "refused"
    assert requests_db.get_request(ref)["decided_at"]


def test_lookup_requires_both():
    ref = requests_db.create_request({"car_number": "AB-1234"}, "msg")["reference"]
    assert requests_db.lookup(ref, "AB1234")
    assert requests_db.lookup(ref, "") is None
    assert requests_db.lookup(ref, "XY-1234") is None
    assert requests_db.lookup("CP-ZZZZZZ", "AB-1234") is None
