import sqlite3
from pathlib import Path

DB_PATH = Path("data/parking.db")


def init_db():
    """Create the SQLite database with prices, hours and availability."""
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    DROP TABLE IF EXISTS prices;
    DROP TABLE IF EXISTS availability;
    DROP TABLE IF EXISTS hours;

    CREATE TABLE prices(space_type TEXT, price_per_hour REAL);
    CREATE TABLE availability(date TEXT, free_spaces INTEGER);
    CREATE TABLE hours(days TEXT, open_time TEXT, close_time TEXT);

    INSERT INTO prices VALUES ('standard', 3.0), ('covered', 5.0), ('ev_charging', 6.5);
    INSERT INTO availability VALUES
        ('2026-11-25', 42), ('2026-11-26', 35), ('2026-11-27', 12),
        ('2026-11-28', 0),  ('2026-11-29', 20), ('2026-11-30', 8),
        ('2026-12-01', 15), ('2026-12-02', 0),  ('2026-12-03', 30);
    INSERT INTO hours VALUES ('Mon-Fri', '06:00', '22:00'), ('Sat-Sun', '08:00', '20:00');
    """)
    con.commit()
    con.close()


def get_dynamic_context() -> str:
    """Return prices, hours and availability as readable text for the LLM."""
    con = sqlite3.connect(DB_PATH)
    lines = ["PRICES (per hour):"]
    for t, p in con.execute("SELECT space_type, price_per_hour FROM prices"):
        lines.append(f"- {t}: {p} EUR")
    lines.append("WORKING HOURS:")
    for d, o, c in con.execute("SELECT days, open_time, close_time FROM hours"):
        lines.append(f"- {d}: {o} to {c}")
    lines.append("AVAILABLE DATES (free spaces > 0):")
    for d, n in con.execute(
        "SELECT date, free_spaces FROM availability WHERE free_spaces > 0 ORDER BY date"
    ):
        lines.append(f"- {d}: {n} free space(s)")
    lines.append("FULLY BOOKED DATES:")
    for d, n in con.execute(
        "SELECT date, free_spaces FROM availability WHERE free_spaces = 0 ORDER BY date"
    ):
        lines.append(f"- {d}: fully booked")
    con.close()
    return "\n".join(lines)


def get_available_slots() -> str:
    """Return dates that still have free spaces, with count."""
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT date, free_spaces FROM availability WHERE free_spaces > 0 ORDER BY date"
    ).fetchall()
    con.close()
    if not rows:
        return "No free spaces are currently available."
    lines = ["AVAILABLE DATES AND FREE SPACES:"]
    for date, spaces in rows:
        lines.append(f"- {date}: {spaces} free space(s)")
    return "\n".join(lines)
