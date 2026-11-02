import time
import statistics
import requests
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
from concurrent.futures import ThreadPoolExecutor

from src.rag.vector_store import load_retriever
from src.rag.chatbot import chat_turn, Reservation
from mcp_server.server import write_reservation
import os

ADMIN_URL = "http://localhost:8001"
N = 20          # number of parallel requests
WORKERS = 5


def timed(fn, *args):
    start = time.perf_counter()
    try:
        fn(*args)
        ok = True
    except Exception as e:
        print("error:", e)
        ok = False
    return time.perf_counter() - start, ok


def report(name, results):
    times = [t for t, _ in results]
    ok = sum(1 for _, o in results if o)
    print(f"{name:<28} n={len(results)} ok={ok} "
          f"avg={statistics.mean(times)*1000:.0f}ms "
          f"p95={sorted(times)[int(len(times)*0.95)-1]*1000:.0f}ms "
          f"max={max(times)*1000:.0f}ms")


def chat_call(_):
    chat_turn("How much is covered parking?", Reservation(), False)


def admin_call(_):
    r = requests.post(f"{ADMIN_URL}/requests", json={"test": True}, timeout=10)
    rid = r.json()["id"]
    requests.post(f"{ADMIN_URL}/requests/{rid}/decision", json={"approved": True}, timeout=10)


def mcp_call(i):
    res = write_reservation(f"Load{i} Test", "LT-1234", "2026-11-05 from 09:00 to 18:00",
                            os.environ["MCP_SECRET"])
    assert res.startswith("OK")


if __name__ == "__main__":
    for name, fn in [("Chatbot (RAG, info mode)", chat_call),
                     ("Admin API (create+decide)", admin_call),
                     ("MCP file writer", mcp_call)]:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            results = list(ex.map(lambda i: timed(fn, i), range(N)))
        report(name, results)