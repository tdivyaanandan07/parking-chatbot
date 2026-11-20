import os
import re
from datetime import datetime
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.booking import find_conflict

load_dotenv()

mcp = FastMCP("reservation-writer")
FILE = os.environ.get("RESERVATIONS_FILE", "reservations.txt")
SECRET = os.environ.get("MCP_SECRET", "")


def clean(s: str) -> str:
    """Remove characters that could break the file format."""
    return re.sub(r"[|\n\r]", " ", s).strip()[:100]


def write_reservation(name: str, car_number: str, period: str, token: str,
                      reference: str = "") -> str:
    """Core logic (a plain function so it is easy to test)."""
    if not SECRET or token != SECRET:
        return "ERROR: unauthorized"
    if not re.fullmatch(r"[A-Za-z0-9\- ]{3,12}", (car_number or "").strip()):
        return "ERROR: invalid car number"
    approved_at = datetime.now().isoformat(timespec="seconds")
    line = f"{clean(name)} | {clean(car_number)} | {clean(period)} | {approved_at}"
    if reference:
        line += f" | {clean(reference)}"
    line += "\n"
    conflict = find_conflict(car_number, period, FILE)
    if conflict:
        return "ERROR: overlapping booking exists for this car"
    with open(FILE, "a", encoding="utf-8") as f:
        f.write(line)
    return "OK: saved"


@mcp.tool()
def save_reservation(name: str, car_number: str, period: str, token: str,
                     reference: str = "") -> str:
    """Save an APPROVED parking reservation to the text file."""
    return write_reservation(name, car_number, period, token, reference)


if __name__ == "__main__":
    mcp.run()  # stdio: runs only as a local child process, no open network port