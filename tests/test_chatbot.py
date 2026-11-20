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

from unittest.mock import patch, MagicMock
from src.rag import chatbot
from src.rag.chatbot import Turn, chat_turn


def _stub_llm(turn):
    m = MagicMock()
    m.with_structured_output.return_value.invoke.return_value = turn
    return m


def test_multiple_fields_in_one_message():
    turn = Turn(intent="reserve", name="John", surname="Smith",
                car_number="ABC123", period="tomorrow 9am to 5pm")
    with patch.object(chatbot, "llm", _stub_llm(turn)):
        reply, draft, collecting, ready = chat_turn(
            "I'm John Smith, plate ABC123, tomorrow 9am to 5pm",
            Reservation(), collecting=True)
    assert (draft.name, draft.surname, draft.car_number) == ("John", "Smith", "ABC123")
    # complete -> summary shown and confirmation requested, not submitted yet
    assert draft.period and collecting and not ready
    assert "Please check your reservation" in reply and "ABC123" in reply


def test_partial_multi_field_then_asks_for_rest():
    turn = Turn(intent="reserve", name="Jane", car_number="XY9988")
    with patch.object(chatbot, "llm", _stub_llm(turn)):
        reply, draft, _, ready = chat_turn(
            "Jane, car XY9988", Reservation(), collecting=False)
    assert draft.name == "Jane" and draft.car_number == "XY9988"
    assert not ready and "surname" in reply and "period" in reply


def test_single_field_answer_uses_raw_words_for_period():
    # LLM trims the period; the raw message is the fuller, authoritative answer.
    turn = Turn(intent="reserve", period="tomorrow")
    draft0 = Reservation(name="A", surname="B", car_number="CC11")
    with patch.object(chatbot, "llm", _stub_llm(turn)):
        reply, draft, _, ready = chat_turn(
            "tomorrow 12 noon to 4pm", draft0, collecting=True)
    assert draft.period and not ready and "Please check" in reply


# --- confirmation step ---

FULL = Reservation(name="Ann", surname="Lee", car_number="AB-1234",
                   period="2099-11-05 09:00 to 18:00")


def test_yes_and_no_detection():
    for m in ["yes", "Yes please!", "ok", "go ahead", "looks good", "confirm", "y"]:
        assert chatbot.is_yes(m), m
    for m in ["no", "Cancel", "cancel the booking please", "nope", "never mind"]:
        assert chatbot.is_no(m), m
    for m in ["no, change the car to XY123", "yes but change the time", "not good"]:
        assert not chatbot.is_yes(m) and not chatbot.is_no(m), m


def test_yes_submits_without_calling_llm():
    llm = MagicMock()
    with patch.object(chatbot, "llm", llm):
        _, draft, collecting, ready = chat_turn("yes", FULL, collecting=True)
    assert ready and not collecting and draft == FULL
    llm.with_structured_output.assert_not_called()


def test_yes_with_expired_period_asks_again():
    old = FULL.model_copy(update={"period": "2020-01-01 09:00 to 10:00"})
    reply, draft, collecting, ready = chat_turn("yes", old, collecting=True)
    assert not ready and collecting and draft.period is None and "passed" in reply


def test_no_cancels_the_draft():
    reply, draft, collecting, ready = chat_turn("cancel", FULL, collecting=True)
    assert not ready and not collecting and draft == Reservation() and "cancelled" in reply


def test_correction_updates_and_reshows_summary():
    turn = Turn(intent="reserve", car_number="XY-9988")
    with patch.object(chatbot, "llm", _stub_llm(turn)):
        reply, draft, collecting, ready = chat_turn(
            "no, change the car to XY-9988", FULL, collecting=True)
    assert draft.car_number == "XY-9988" and draft.name == "Ann"
    assert collecting and not ready and reply.startswith("Updated") and "XY-9988" in reply


def test_reminder_when_confirming():
    assert "confirmation" in chatbot._reminder(FULL)


# --- status check ---

STORED = {"reference": "CP-7K3F9Q", "status": "approved",
          "details": {"reservation": FULL.model_dump(), "message": "m"}}


def test_status_with_reference_and_car():
    turn = Turn(intent="status", car_number="AB-1234")
    with patch.object(chatbot, "llm", _stub_llm(turn)), \
         patch.object(chatbot, "check_status", return_value=STORED) as cs:
        reply, draft, collecting, ready = chat_turn(
            "status of cp-7k3f9q for car AB-1234", Reservation(), collecting=False)
    cs.assert_called_once_with("CP-7K3F9Q", "AB-1234")
    assert "CP-7K3F9Q" in reply and "approved" in reply and not ready


def test_status_needs_car_number():
    turn = Turn(intent="status", reference="CP-7K3F9Q")
    with patch.object(chatbot, "llm", _stub_llm(turn)), \
         patch.object(chatbot, "check_status") as cs:
        reply, *_ = chat_turn("status of CP-7K3F9Q", Reservation(), collecting=False)
    cs.assert_not_called()
    assert "car number plate" in reply


def test_status_not_found_is_generic():
    turn = Turn(intent="status", car_number="ZZ-9999")
    with patch.object(chatbot, "llm", _stub_llm(turn)), \
         patch.object(chatbot, "check_status", return_value=None):
        reply, *_ = chat_turn("status CP-7K3F9Q car ZZ-9999", Reservation(), collecting=False)
    assert "couldn't find" in reply


def test_status_mid_booking_keeps_draft():
    turn = Turn(intent="status", car_number="AB-1234")
    partial = Reservation(name="Ann")
    with patch.object(chatbot, "llm", _stub_llm(turn)), \
         patch.object(chatbot, "check_status", return_value=STORED):
        reply, draft, collecting, _ = chat_turn(
            "status of CP-7K3F9Q for car AB-1234", partial, collecting=True)
    assert draft == partial and collecting and "still booking" in reply


# --- graph submit node ---

from src import graph


def test_submit_node_returns_reference_and_resets():
    with patch.object(graph, "submit_for_approval", return_value="CP-7K3F9Q"):
        out = graph.submit_node({"draft": FULL})
    assert out["reference"] == "CP-7K3F9Q" and "CP-7K3F9Q" in out["reply"]
    assert out["draft"] == Reservation() and not out["collecting"]


def test_submit_node_failure_keeps_draft_for_retry():
    with patch.object(graph, "submit_for_approval", side_effect=ConnectionError):
        out = graph.submit_node({"draft": FULL})
    assert "draft" not in out and out["collecting"] and "try again" in out["reply"]


from src.db.sql_db import get_dynamic_context, get_available_slots

def test_available_slots_returns_future_dates():
    result = get_available_slots()
    assert "2026-11-25" in result
    assert "free space" in result

def test_fully_booked_not_in_available_slots():
    result = get_available_slots()
    assert "2026-11-28" not in result  # fully booked date