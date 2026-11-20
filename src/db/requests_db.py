import re
import secrets
import sqlite3
from datetime import datetime
from typing import Optional

from src.db.sql_db import DB_PATH
from src.booking import normalize_car

# No 0/O or 1/I, so a reference can be read out or typed without confusion.
REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
REF_PREFIX = "CP-"
REF_LEN = 6
REF_RE = re.compile(rf"\bCP-?([{REF_ALPHABET}]{{{REF_LEN}}})\b", re.IGNORECASE)

# Statuses: pending -> approved | refused, or save_failed if approved but MCP couldn't write it.
SCHEMA = """
CREATE TABLE IF NOT EXISTS reservation_requests(
    reference  TEXT PRIMARY KEY,
    name       TEXT,
    surname    TEXT,
    car_number TEXT,
    period     TEXT,
    message    TEXT,
    status     TEXT NOT NULL DEFAULT 'pending',
    note       TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    thread_id  TEXT
)
"""
# thread_id: the LangGraph run paused at admin_approval for this request, if any.


def _connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(reservation_requests)")}
    if "thread_id" not in cols:  # databases created before the graph owned approvals
        con.execute("ALTER TABLE reservation_requests ADD COLUMN thread_id TEXT")
    return con


def new_reference() -> str:
    return REF_PREFIX + "".join(secrets.choice(REF_ALPHABET) for _ in range(REF_LEN))


def parse_reference(text: str) -> Optional[str]:
    """Find a reference like 'CP-7K3F9Q' (or 'cp7k3f9q') in text, in canonical form."""
    m = REF_RE.search(text or "")
    return REF_PREFIX + m.group(1).upper() if m else None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_request(reservation: dict, message: str, thread_id: Optional[str] = None) -> dict:
    """Store a new pending request under a fresh, unique reference number."""
    con = _connect()
    try:
        while True:
            ref = new_reference()
            try:
                con.execute(
                    "INSERT INTO reservation_requests"
                    "(reference, name, surname, car_number, period, message, created_at,"
                    " thread_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (ref, reservation.get("name"), reservation.get("surname"),
                     reservation.get("car_number"), reservation.get("period"),
                     message, _now(), thread_id))
                con.commit()
                break
            except sqlite3.IntegrityError:
                continue  # reference collision, draw another one
    finally:
        con.close()
    return get_request(ref)


def get_request(reference: str) -> Optional[dict]:
    con = _connect()
    try:
        row = con.execute("SELECT * FROM reservation_requests WHERE reference = ?",
                          (reference,)).fetchone()
    finally:
        con.close()
    return dict(row) if row else None


def pending_requests() -> list[dict]:
    con = _connect()
    try:
        rows = con.execute("SELECT * FROM reservation_requests WHERE status = 'pending'"
                           " ORDER BY created_at").fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def set_status(reference: str, status: str, note: Optional[str] = None) -> Optional[dict]:
    con = _connect()
    try:
        con.execute("UPDATE reservation_requests SET status = ?, note = ?, decided_at = ?"
                    " WHERE reference = ?", (status, note, _now(), reference))
        con.commit()
    finally:
        con.close()
    return get_request(reference)


def lookup(reference: str, car_number: str) -> Optional[dict]:
    """Return the request only if BOTH the reference and its car number match.

    A wrong reference and a wrong car number give the same None, so a caller
    can't learn whether a reference exists without knowing the car as well.
    """
    ref = parse_reference(reference)
    if not ref or not car_number:
        return None
    req = get_request(ref)
    if not req or normalize_car(req["car_number"] or "") != normalize_car(car_number):
        return None
    return req
