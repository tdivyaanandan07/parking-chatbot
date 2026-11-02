import time
import requests
from src.config import llm

ADMIN_URL = "http://localhost:8001"


def request_approval(reservation: dict, timeout_s: int = 300) -> str:
    """Agent 2: write a message for the admin, send it, wait for the human's answer.
    Returns 'approved', 'refused' or 'timeout'."""
    message = llm.invoke(
        "Write a short, polite approval request (2-3 sentences) for a parking "
        f"administrator about this reservation: {reservation}"
    ).content

    r = requests.post(f"{ADMIN_URL}/requests",
                      json={"reservation": reservation, "message": message}, timeout=10)
    rid = r.json()["id"]
    print(f"\n[Agent 2] Sent to admin (id {rid[:8]}). Waiting for decision...")

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = requests.get(f"{ADMIN_URL}/requests/{rid}", timeout=10).json()["status"]
        if status != "pending":
            return status
        time.sleep(2)
    return "timeout"