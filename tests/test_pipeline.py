"""Integration tests: one booking through every node of the LangGraph pipeline.

chat -> submit (agent 2 -> admin API) -> admin_approval (paused) -> decision via
the admin API -> record (real MCP server over stdio) -> reservations file.

Only the LLM is stubbed. The admin API runs in-process, and the agent's HTTP
calls go to it. The graph uses a SQLite checkpoint file, and the decision is
resumed on a freshly built graph, as it is in the separate admin API process.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src import graph
from src.admin import agent, api
from src.db import requests_db
from src.rag import chatbot
from src.rag.chatbot import Reservation, Turn

FULL = Reservation(name="Ann", surname="Lee", car_number="AB-1234",
                   period="2099-11-05 09:00 to 18:00")


class _ToInbox:
    """Stands in for `requests` inside the agent: sends its calls to the in-process API."""

    def __init__(self, client):
        self.client = client

    def post(self, url, json=None, timeout=None):
        return self.client.post(url.replace(agent.ADMIN_URL, ""), json=json)


def _graph(path):
    return graph.build_graph(graph.sqlite_checkpointer(path))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(requests_db, "DB_PATH", tmp_path / "requests.db")
    monkeypatch.setattr(graph, "app", _graph(tmp_path / "checkpoints.db"))
    monkeypatch.setattr(agent, "requests", _ToInbox(TestClient(api.app)))
    monkeypatch.setattr(agent, "llm", MagicMock(**{"invoke.return_value.content": "Please approve."}))
    # The MCP server is a child process; it reads these from its environment.
    monkeypatch.setenv("MCP_SECRET", "pipeline-secret")
    monkeypatch.setenv("RESERVATIONS_FILE", str(tmp_path / "reservations.txt"))
    return tmp_path


def _confirm_booking():
    """The customer says yes to a complete summary."""
    return graph.run_turn("yes", FULL, collecting=True)


def _admin_process(env):
    """The admin API runs in another process with its own graph on the same checkpoints."""
    graph.app = _graph(env / "checkpoints.db")


def _decide(ref, approved):
    return TestClient(api.app).post(f"/requests/{ref}/decision", json={"approved": approved}).json()


def _status_reply(ref):
    turn = Turn(intent="status", car_number=FULL.car_number)
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = turn
    with patch.object(chatbot, "llm", llm):
        return graph.run_turn(f"status of {ref} for car {FULL.car_number}",
                              Reservation(), collecting=False)["reply"]


def test_approved_booking_runs_every_node_and_is_recorded(env):
    out = _confirm_booking()
    ref = out["reference"]

    # The customer has a reference at once; the run waits at admin_approval.
    assert ref and ref in out["reply"] and out["__interrupt__"]
    assert out["draft"] == Reservation() and not out["collecting"]
    req = requests_db.get_request(ref)
    assert req["status"] == "pending" and req["message"] == "Please approve."
    config = {"configurable": {"thread_id": req["thread_id"]}}
    assert graph.app.get_state(config).next == ("admin_approval",)
    assert "waiting for the administrator" in _status_reply(ref)

    _admin_process(env)
    assert _decide(ref, True)["status"] == "approved"

    line = (env / "reservations.txt").read_text().strip()
    assert line.startswith("Ann Lee | AB-1234 | 2099-11-05 09:00 to 18:00 |")
    assert line.endswith(f"| {ref}")
    assert graph.app.get_state(config).next == ()  # run finished
    assert "**approved**" in _status_reply(ref)


def test_refused_booking_ends_without_recording(env):
    ref = _confirm_booking()["reference"]
    _admin_process(env)
    assert _decide(ref, False)["status"] == "refused"
    assert not (env / "reservations.txt").exists()
    assert "**refused**" in _status_reply(ref)


def test_overlapping_booking_is_reported_as_save_failed(env):
    (env / "reservations.txt").write_text(
        "Bob Ray | AB 1234 | 2099-11-05 08:00 to 10:00 | 2099-01-01T00:00:00 | CP-AAAAAA\n")
    ref = _confirm_booking()["reference"]
    res = _decide(ref, True)
    assert res["status"] == "save_failed" and "overlapping" in res["note"]
    assert len((env / "reservations.txt").read_text().splitlines()) == 1


def test_decision_cannot_resume_twice(env):
    ref = _confirm_booking()["reference"]
    _decide(ref, False)
    r = TestClient(api.app).post(f"/requests/{ref}/decision", json={"approved": True})
    assert r.status_code == 409


def test_unconfirmed_turn_stops_after_chat(env):
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = Turn(intent="reserve", name="Ann")
    with patch.object(chatbot, "llm", llm):
        out = graph.run_turn("I'd like to book, I'm Ann", Reservation(), collecting=False)
    assert "__interrupt__" not in out and out["reference"] is None
    assert out["draft"].name == "Ann" and out["collecting"]
    assert requests_db.pending_requests() == []


def test_unreachable_admin_keeps_draft_and_does_not_pause(env, monkeypatch):
    def down(*a, **k):
        raise ConnectionError
    monkeypatch.setattr(agent.requests, "post", down)
    out = _confirm_booking()
    assert "__interrupt__" not in out and out["reference"] is None
    assert out["draft"] == FULL and out["collecting"] and "try again" in out["reply"]
