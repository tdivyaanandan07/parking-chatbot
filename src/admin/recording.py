from src.db import requests_db
from src.mcp_client import save_via_mcp


def record_approved(reference: str) -> dict:
    """Write an approved request to the reservations file through the MCP server
    and store the outcome: approved, or save_failed with the reason."""
    req = requests_db.get_request(reference)
    try:
        result = save_via_mcp(f"{req['name']} {req['surname']}", req["car_number"],
                              req["period"], reference)
    except Exception as e:
        result = f"ERROR: {e}"
    if "OK" in result:
        return requests_db.set_status(reference, "approved")
    return requests_db.set_status(reference, "save_failed", result)
