from src.rag.chatbot import Reservation, looks_valid
from datetime import datetime
from src.rag.chatbot import Reservation, looks_valid, check_period, canonicalize_period

def test_missing_fields():
    r = Reservation(name="A")
    assert r.missing() == ["surname", "car_number", "period"]


def test_period_validation():
    assert looks_valid("period", "2099-11-04 from 05:30 to 16:00")
    assert not looks_valid("period", "tomorrow at 3pm")
    assert not looks_valid("period", "2020-01-01 from 09:00 to 18:00")

NOW = datetime(2026, 11, 19, 12, 0)

def test_past_date_rejected():
    ok, msg = check_period("2026-11-01 from 10:00 to 15:00", now=NOW)
    assert not ok and "past" in msg

def test_future_date_accepted():
    assert check_period("2026-11-25 from 10:00 to 15:00", now=NOW)[0]

def test_end_before_start_rejected():
    assert not check_period("2026-11-25 from 15:00 to 10:00", now=NOW)[0]

def test_bad_format_rejected():
    assert not check_period("tomorrow at 3pm", now=NOW)[0]


# NOW is Thursday 2026-11-19 12:00 in these tests.

def test_human_period_accepted():
    assert check_period("tomorrow 12 noon to 4pm", now=NOW)[0]
    assert check_period("for tomorrow 12 noon to 4pm", now=NOW)[0]
    assert check_period("next monday 3-5pm", now=NOW)[0]
    assert check_period("25 nov 14:00 to 16:00", now=NOW)[0]
    assert check_period("tomorrow 10am for 2 hours", now=NOW)[0]
    assert check_period("this friday evening", now=NOW)[0]  # Fri 18:00 is after NOW (Thu 12:00)


def test_human_period_canonicalized():
    assert canonicalize_period("tomorrow 12 noon to 4pm", now=NOW) == "2026-11-20 12:00 to 16:00"
    assert canonicalize_period("next monday 3-5pm", now=NOW) == "2026-11-23 15:00 to 17:00"
    # crossing midnight keeps both dates so booking.py can parse it back
    assert canonicalize_period("tomorrow 9pm to 2am", now=NOW) == "2026-11-20 21:00 to 2026-11-21 02:00"


def test_human_period_needs_an_end():
    # a lone start time is still not a valid period
    assert not check_period("tomorrow at 3pm", now=NOW)[0]
    assert canonicalize_period("tomorrow at 3pm", now=NOW) is None

from src.db.sql_db import get_dynamic_context, get_available_slots

def test_available_slots_returns_future_dates():
    result = get_available_slots()
    assert "2026-11-25" in result
    assert "free space" in result

def test_fully_booked_not_in_available_slots():
    result = get_available_slots()
    assert "2026-11-28" not in result  # fully booked date