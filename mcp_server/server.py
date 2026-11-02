import os
import re
from datetime import datetime
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("reservation-writer")
FILE = "reservations.txt"
SECRET = os.environ.get("MCP_SECRET", "")


def clean(s: str) -> str:
    """Remove characters that could break the file format."""
    return re.sub(r"[|\n\r]", " ", s).strip()[:100]


def write_reservation(name: str, car_number: str, period: str, token: str) -> str:
    """Core logic (a plain function so it is easy to test)."""
    if not SECRET or token != SECRET:
        return "ERROR: unauthorized"
    if not re.fullmatch(r"[A-Za-z0-9\- ]{3,12}", car_number.strip()):
        return "ERROR: invalid car number"
    approved_at = datetime.now().isoformat(timespec="seconds")
    line = f"{clean(name)} | {clean(car_number)} | {clean(period)} | {approved_at}\n"
    with open(FILE, "a", encoding="utf-8") as f:
        f.write(line)
    return "OK: saved"


@mcp.tool()
def save_reservation(name: str, car_number: str, period: str, token: str) -> str:
    """Save an APPROVED parking reservation to the text file."""
    return write_reservation(name, car_number, period, token)


if __name__ == "__main__":
    mcp.run()  # stdio: runs only as a local child process, no open network port