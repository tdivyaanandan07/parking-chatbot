from typing import Optional
import requests
from src.config import llm

ADMIN_URL = "http://localhost:8001"


def submit_for_approval(reservation: dict) -> str:
    """Agent 2: write a message for the admin and send it to the admin inbox.

    Does not wait for the decision; returns the reference number the customer
    can later use (with their car number) to check the status.
    """
    message = llm.invoke(
        "Write a short, polite approval request (2-3 sentences) for a parking "
        f"administrator about this reservation: {reservation}"
    ).content

    r = requests.post(f"{ADMIN_URL}/requests",
                      json={"reservation": reservation, "message": message}, timeout=10)
    r.raise_for_status()
    ref = r.json()["reference"]
    print(f"\n[Agent 2] Sent to admin, reference {ref}.")
    return ref


def check_status(reference: str, car_number: str) -> Optional[dict]:
    """Return the request if the reference and car number match, else None."""
    r = requests.post(f"{ADMIN_URL}/requests/lookup",
                      json={"reference": reference, "car_number": car_number}, timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()
