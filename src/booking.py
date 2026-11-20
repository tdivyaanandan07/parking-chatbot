import re
from datetime import datetime
from pathlib import Path

RESERVATIONS_FILE = "reservations.txt"

# Matches "2026-11-05 from 09:00 to 18:00" and "2026-11-05 09:00 to 2026-11-06 10:00"
PERIOD_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s+(?:from\s+)?(\d{2}:\d{2})\s+to\s+(?:(\d{4}-\d{2}-\d{2})\s+)?(\d{2}:\d{2})"
)


def parse_period(text: str):
    """Return (start, end) as datetimes, or None if the text is not a valid period."""
    if not text:
        return None
    m = PERIOD_RE.search(text)
    if not m:
        return None
    d1, t1, d2, t2 = m.groups()
    d2 = d2 or d1
    try:
        start = datetime.strptime(f"{d1} {t1}", "%Y-%m-%d %H:%M")
        end = datetime.strptime(f"{d2} {t2}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    if end <= start:
        return None
    return start, end


def normalize_car(car: str) -> str:
    """'ab-1234' and 'AB 1234' both become 'AB1234'."""
    return re.sub(r"[\s-]", "", car).upper()


def overlaps(a, b) -> bool:
    """Two (start, end) ranges overlap if each starts before the other ends."""
    return a[0] < b[1] and b[0] < a[1]


def existing_bookings(path: str = RESERVATIONS_FILE):
    """Read reservations.txt and return (car, (start, end), line) for each valid row."""
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 4:
            continue
        car, period = parts[1], parts[2]
        parsed = parse_period(period)
        if parsed:
            rows.append((normalize_car(car), parsed, line))
    return rows


def find_conflict(car: str, period_text: str, path: str = RESERVATIONS_FILE):
    """Return the existing line that overlaps this car's new period, or None."""
    new = parse_period(period_text)
    if not new:
        return None
    car_n = normalize_car(car)
    for other_car, other_period, line in existing_bookings(path):
        if other_car == car_n and overlaps(new, other_period):
            return line
    return None