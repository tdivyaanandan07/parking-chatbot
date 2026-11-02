from src.rag.chatbot import Reservation, looks_valid


def test_missing_fields():
    r = Reservation(name="A")
    assert r.missing() == ["surname", "car_number", "period"]


def test_period_validation():
    assert looks_valid("period", "2026-11-04 from 05:30 to 16:00")
    assert not looks_valid("period", "tomorrow at 3pm")