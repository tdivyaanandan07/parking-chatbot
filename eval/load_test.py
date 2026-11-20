"""Load test of each component and of the whole orchestrated pipeline.

    python -m eval.load_test

Everything a run writes (requests DB, graph checkpoints, reservations file) goes
to a temporary folder, so real bookings are never touched and the admin inbox
doesn't need to be running: the admin API is called in-process through FastAPI's
TestClient. The LLM (DIAL) and the MCP server (stdio child process) are real.
"""
import logging
import os
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)

TMP = Path(tempfile.mkdtemp(prefix="parking-load-"))
os.environ["RESERVATIONS_FILE"] = str(TMP / "reservations.txt")  # read by the MCP server

from fastapi.testclient import TestClient  # noqa: E402

from src import graph  # noqa: E402
from src.admin import agent, api  # noqa: E402
from src.db import requests_db  # noqa: E402
from src.mcp_client import save_via_mcp  # noqa: E402
from src.rag.chatbot import Reservation  # noqa: E402
from mcp_server.server import write_reservation  # noqa: E402

N = 20          # requests per component
WORKERS = 5     # in parallel
PERIOD = "2099-11-05 09:00 to 18:00"

requests_db.DB_PATH = TMP / "requests.db"
graph.app = graph.build_graph(graph.sqlite_checkpointer(TMP / "checkpoints.db"))
inbox = TestClient(api.app)


class _ToInbox:
    """Stands in for `requests` inside agent 2: sends its calls to the in-process API."""

    def post(self, url, json=None, timeout=None):
        return inbox.post(url.replace(agent.ADMIN_URL, ""), json=json)


agent.requests = _ToInbox()


def timed(fn, *args):
    start = time.perf_counter()
    try:
        result, ok = fn(*args), True
    except Exception as e:
        print("error:", e)
        result, ok = None, False
    return time.perf_counter() - start, ok, result


def report(name, results):
    times = [t for t, _, _ in results]
    ok = sum(1 for _, o, _ in results if o)
    print(f"{name:<38} n={len(results):<3} ok={ok:<3} "
          f"avg={statistics.mean(times)*1000:>6.0f}ms "
          f"p95={sorted(times)[int(len(times)*0.95)-1]*1000:>6.0f}ms "
          f"max={max(times)*1000:>6.0f}ms")


def run(name, fn, items):
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(lambda i: timed(fn, i), items))
    report(name, results)
    return [r for _, ok, r in results if ok]


def chat_call(_):
    """Chatbot in interactive dialogue mode: an info question through the graph."""
    graph.run_turn("How much is covered parking?", Reservation(), False)


def submit_call(i):
    """Customer confirms a booking: chat -> submit (agent 2 + inbox) -> paused."""
    draft = Reservation(name="Load", surname=f"Test{i}", car_number=f"LP{i:04d}", period=PERIOD)
    out = graph.run_turn("yes", draft, True)
    assert out["reference"] and out.get("__interrupt__"), out["reply"]
    return out["reference"]


def decide_call(approved):
    def call(ref):
        status = inbox.post(f"/requests/{ref}/decision", json={"approved": approved}).json()["status"]
        assert status == ("approved" if approved else "refused"), status
    return call


def mcp_stdio_call(i):
    res = save_via_mcp(f"Load{i} Mcp", f"LM{i:04d}", PERIOD, "")
    assert "OK" in res, res  # the tool result comes back as content blocks


def mcp_logic_call(i):
    res = write_reservation(f"Load{i} Logic", f"LL{i:04d}", PERIOD, os.environ["MCP_SECRET"])
    assert res.startswith("OK"), res


if __name__ == "__main__":
    print(f"Data folder for this run: {TMP}\n")
    run("Chatbot dialogue (graph: chat)", chat_call, range(N))
    refs = run("Booking submit (chat->submit->pause)", submit_call, range(2 * N))
    run("Admin refuse (resume -> END)", decide_call(False), refs[:N])
    run("Admin approve (resume -> record/MCP)", decide_call(True), refs[N:])
    run("MCP server, stdio round trip", mcp_stdio_call, range(N))
    run("MCP writer logic only", mcp_logic_call, range(N))

    # Stable operation: every approval and direct MCP write is in the file exactly once.
    lines = Path(os.environ["RESERVATIONS_FILE"]).read_text().splitlines()
    approved = {r for r in refs[N:]}
    recorded = {ln.rsplit(" | ", 1)[-1] for ln in lines if ln.startswith("Load Test")}
    statuses = {}
    for ref in refs:
        s = requests_db.get_request(ref)["status"]
        statuses[s] = statuses.get(s, 0) + 1
    print(f"\nStatuses: {statuses}")
    print(f"Reservations file: {len(lines)} lines; approved bookings recorded: "
          f"{len(recorded & approved)}/{len(approved)}; unexpected: {len(recorded - approved)}")
