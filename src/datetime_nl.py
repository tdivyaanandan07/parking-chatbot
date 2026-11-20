"""Parse human-friendly booking periods into exact (start, end) datetimes.

Understands phrases such as:
    "tomorrow 12 noon to 4pm"
    "next monday 3-5pm"
    "today from 9am to 11:30am"
    "25 nov 14:00 to 16:00"
    "this friday evening"
    "tomorrow 9pm to 2am"          (crosses midnight)
    "tomorrow 10am for 2 hours"

A period MUST have both a start and an end (via "to"/"-", a part of day, or a
"for <duration>"). A lone time like "tomorrow at 3pm" is intentionally rejected
so the chatbot keeps asking for a full period.
"""

import re
from datetime import datetime, timedelta
from dateutil import parser as _du

WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

# (start_hour, end_hour) for a vague part of the day
PARTS_OF_DAY = {
    "morning": (9, 12),
    "noon": (12, 13),
    "midday": (12, 13),
    "afternoon": (13, 17),
    "evening": (18, 21),
    "night": (20, 23),
    "tonight": (18, 21),
}

_WORD_SEP = re.compile(r"\s+(?:to|until|till|through|thru)\s+", re.IGNORECASE)
_DASH_SEP = re.compile(r"\s*[-–—]\s*")
_DURATION_RE = re.compile(
    r"\bfor\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)\b", re.IGNORECASE
)
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def parse_human_period(text: str, now: datetime | None = None):
    """Return (start, end) datetimes, or None if the text is not a full period."""
    if not text:
        return None
    now = now or datetime.now()
    t = _clean(text)

    # A date can trail the whole phrase: "between 1pm and 3pm tomorrow".
    t, trailing = _strip_trailing_date(t, now)
    base_default = trailing or now.date()

    # "<start> for 2 hours"
    dur = _DURATION_RE.search(t)
    if dur:
        minutes = _duration_minutes(dur)
        head = t[: dur.start()].strip(" ,;")
        base, rest = _take_date(head, now, base_default)
        start = _time_on(base, rest)
        if start is None:
            return None
        return _finish(start, start + timedelta(minutes=minutes), now)

    # Split "<start> to <end>"
    parts = _split_range(t)
    if len(parts) != 2:
        # Maybe just a part-of-day with a date, e.g. "this friday evening"
        return _part_of_day_only(t, now, base_default)

    left, right = parts
    start_date, left_rest = _take_date(left, now, base_default)
    # The end inherits the start's date unless it names its own.
    end_date, right_rest = _take_date(right, now, start_date)

    start = _time_on(start_date, left_rest)
    end = _time_on(end_date, right_rest)
    if start is None or end is None:
        # e.g. "friday morning to friday evening"
        return _part_of_day_range(start_date, left_rest, end_date, right_rest, now)

    # Share a meridiem: "3-5pm" -> 3pm-5pm.
    if not _has_meridiem(left_rest) and _has_meridiem(right_rest) and _bare_hour(left_rest):
        start = _reinterpret_meridiem(start, right_rest)

    # Crossed midnight on the same stated day ("9pm to 2am").
    if end <= start and _same_day(left, right, start_date, end_date):
        end += timedelta(days=1)

    return _finish(start, end, now)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _clean(text: str) -> str:
    t = " ".join(text.strip().lower().split())
    t = re.sub(r"[.,;]+$", "", t)
    # drop polite / filler lead-ins
    t = re.sub(r"^(please\s+|can you\s+|could you\s+)", "", t)
    t = re.sub(r"^(reserve|book|i want|i'd like|i would like|i need)\s+", "", t)
    t = re.sub(r"^(a slot|parking|the spot|it)\s+", "", t)
    t = re.sub(r"^(for|on|at)\s+", "", t)
    return t.strip()


def _split_range(t: str):
    # "between X and Y"
    m = re.match(r"^between\s+(.*?)\s+and\s+(.*)$", t, re.IGNORECASE)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    # Prefer word separators ("to") so ISO-date dashes are left intact.
    m = _WORD_SEP.search(t)
    if not m:
        m = _DASH_SEP.search(t)
    if not m:
        return [t]
    return [t[: m.start()].strip(), t[m.end():].strip()]


_WEEKDAY_ALT = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_TRAILING_DATE_RE = re.compile(
    r"\s+(day after tomorrow|tomorrow|today|tonight"
    rf"|(?:this|next|coming)\s+(?:{_WEEKDAY_ALT})|(?:{_WEEKDAY_ALT}))$",
    re.IGNORECASE,
)


def _strip_trailing_date(t: str, now: datetime):
    """Pull a date reference off the end of the phrase, if any."""
    m = _TRAILING_DATE_RE.search(t)
    if not m:
        return t, None
    date, leftover = _take_date(m.group(1), now, now.date())
    if leftover:  # not a clean date phrase, leave it alone
        return t, None
    return t[: m.start()].strip(), date


def _take_date(seg: str, now: datetime, default_date):
    """Pull a leading date reference off `seg`; return (date, remaining_text)."""
    s = re.sub(r"^(from|on|at|starting|start)\s+", "", seg).strip()

    iso = _ISO_DATE_RE.match(s)
    if iso:
        d = datetime.strptime(iso.group(1), "%Y-%m-%d").date()
        return d, s[iso.end():].strip()

    if s.startswith("day after tomorrow"):
        return now.date() + timedelta(days=2), s[len("day after tomorrow"):].strip()
    if s.startswith("tomorrow"):
        return now.date() + timedelta(days=1), s[len("tomorrow"):].strip()
    if s.startswith("today") or s.startswith("tonight"):
        kw = "today" if s.startswith("today") else "tonight"
        rest = s[len(kw):].strip()
        # keep "tonight" so the part-of-day logic can see it
        return now.date(), (("tonight " + rest).strip() if kw == "tonight" else rest)

    m = re.match(r"^(this|next|coming)?\s*([a-z]+)(.*)$", s)
    if m and m.group(2) in WEEKDAYS:
        qualifier, name, rest = m.group(1), m.group(2), m.group(3)
        d = _weekday_date(now, WEEKDAYS[name], qualifier)
        return d, rest.strip()

    # "25 nov", "nov 25", "25/11", "25 november 2026" -> let dateutil try
    md = re.match(
        r"^(\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+(?:\s+\d{4})?"
        r"|[a-z]+\s+\d{1,2}(?:st|nd|rd|th)?(?:\s+\d{4})?"
        r"|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b(.*)$",
        s,
    )
    if md:
        phrase = re.sub(r"(st|nd|rd|th)\b", "", md.group(1))
        try:
            d = _du.parse(phrase, default=now, dayfirst=True).date()
            return d, md.group(2).strip()
        except (ValueError, OverflowError):
            pass

    return default_date, s


def _weekday_date(now, target, qualifier):
    delta = (target - now.weekday()) % 7
    if qualifier == "next":
        delta = delta or 7
    return now.date() + timedelta(days=delta)


def _time_on(date, text: str):
    """Combine a date with a time phrase like '12 noon', '4pm', '16:00'."""
    hm = _parse_time(text)
    if hm is None:
        return None
    return datetime(date.year, date.month, date.day, hm[0], hm[1])


def _parse_time(text: str):
    s = text.strip().strip(".,;").strip()
    s = re.sub(r"^(from|at|to|around|about)\s+", "", s).strip()
    if not s:
        return None

    if s in ("noon", "midday", "12 noon", "12noon"):
        return (12, 0)
    if s in ("midnight", "12 midnight"):
        return (0, 0)
    s = re.sub(r"\bnoon\b", "", s).strip()  # "12 noon" already handled above

    m = re.match(r"^(\d{1,2})(?::|\.|h)?(\d{2})?\s*(a\.?m\.?|p\.?m\.?)?$", s)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    mer = (m.group(3) or "").replace(".", "")

    if mer == "pm" and hour < 12:
        hour += 12
    elif mer == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return (hour, minute)


def _has_meridiem(text: str) -> bool:
    return bool(re.search(r"(?:a\.?m\.?|p\.?m\.?)|\b(?:noon|midnight)\b", text, re.IGNORECASE))


def _bare_hour(text: str) -> bool:
    return bool(re.match(r"^\s*\d{1,2}\s*$", re.sub(r"^(from|at)\s+", "", text.strip())))


def _reinterpret_meridiem(start: datetime, end_text: str) -> datetime:
    """Apply the end's am/pm to a bare start hour ('3-5pm' -> 15:00)."""
    if re.search(r"p\.?m\.?", end_text) and start.hour < 12:
        return start.replace(hour=start.hour + 12)
    if re.search(r"a\.?m\.?", end_text) and start.hour == 12:
        return start.replace(hour=0)
    return start


def _same_day(left: str, right: str, start_date, end_date) -> bool:
    return start_date == end_date and not _ISO_DATE_RE.search(right)


def _duration_minutes(m) -> int:
    value = float(m.group(1))
    unit = m.group(2).lower()
    return int(value * 60) if unit.startswith(("h", "hr")) else int(value)


def _part_of_day_only(t: str, now: datetime, base_default):
    date, rest = _take_date(t, now, base_default)
    return _expand_part_of_day(date, rest, now)


def _part_of_day_range(start_date, left_rest, end_date, right_rest, now):
    left = _expand_part_of_day(start_date, left_rest, now)
    right = _expand_part_of_day(end_date, right_rest, now)
    if not left or not right:
        return None
    return _finish(left[0], right[1], now)


def _expand_part_of_day(date, rest: str, now: datetime):
    word = rest.strip()
    word = re.sub(r"^(in the|the|at|this)\s+", "", word).strip()
    if word not in PARTS_OF_DAY:
        return None
    sh, eh = PARTS_OF_DAY[word]
    start = datetime(date.year, date.month, date.day, sh, 0)
    end = datetime(date.year, date.month, date.day, eh, 0)
    return _finish(start, end, now)


def _finish(start: datetime, end: datetime, now: datetime):
    if end <= start:
        return None
    return start, end
