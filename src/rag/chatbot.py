from typing import Optional, Literal
import re
from pydantic import BaseModel
from src.config import llm
from src.db.sql_db import get_dynamic_context
from src.rag.vector_store import load_retriever
from src.guardrails.filters import redact, is_malicious
from src.datetime_nl import parse_human_period
from src.booking import parse_period
from src.db.requests_db import parse_reference
from src.admin.agent import check_status
from datetime import datetime

_retriever = None


def get_retriever():
    global _retriever
    if _retriever is None:
        _retriever = load_retriever()
    return _retriever


class Reservation(BaseModel):
    name: Optional[str] = None
    surname: Optional[str] = None
    car_number: Optional[str] = None
    period: Optional[str] = None  # e.g. "2026-11-03 09:00 to 2026-11-03 18:00"

    def missing(self) -> list[str]:
        return [k for k, v in self.model_dump().items() if not v]


class Turn(BaseModel):
    intent: Literal["info", "reserve", "status", "other"]
    name: Optional[str] = None
    surname: Optional[str] = None
    car_number: Optional[str] = None
    period: Optional[str] = None
    reference: Optional[str] = None


FIELD_QUESTIONS = {
    "name": "What is your first name?",
    "surname": "What is your surname?",
    "car_number": "What is your car number plate?",
    "period": "For which period do you want to reserve? Please give exact dates and times, e.g. 2026-11-05 from 09:00 to 18:00.",
}

ANSWER_PROMPT = """You are a friendly parking assistant. Answer ONLY using the information below.
If the answer is not there, say you don't know. Keep answers short.

GENERAL INFO:
{static}

LIVE DATA:
{dynamic}

QUESTION: {question}"""

PERIOD_RE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2})\s+(?:from\s+)?(\d{2}:\d{2})\s+to\s+(\d{2}:\d{2})\s*$",
    re.IGNORECASE,
)
PERIOD_HINT = (
    "Please give a date, a start time and an end time, e.g. "
    "'2026-11-25 from 09:00 to 18:00' or 'tomorrow 12 noon to 4pm'."
)


def _period_bounds(text: str, now: datetime):
    """Resolve any accepted period form to (start, end) datetimes, or None.

    Accepts the strict 'YYYY-MM-DD from HH:MM to HH:MM' format and human
    phrases like 'tomorrow 12 noon to 4pm' or 'next monday 3-5pm'.
    """
    m = PERIOD_RE.match(text or "")
    if m:
        day, start_s, end_s = m.groups()
        try:
            start = datetime.strptime(f"{day} {start_s}", "%Y-%m-%d %H:%M")
            end = datetime.strptime(f"{day} {end_s}", "%Y-%m-%d %H:%M")
        except ValueError:
            return "bad-datetime"
        return start, end
    return parse_human_period(text or "", now)


def canonicalize_period(text: str, now: datetime | None = None) -> str | None:
    """Rewrite an accepted period into the stored 'YYYY-MM-DD HH:MM to ...' form.

    Downstream (booking.py, the reservations file) only understands the exact
    format, so human input is normalized here before it is saved.
    """
    now = now or datetime.now()
    bounds = _period_bounds(text, now)
    if not bounds or bounds == "bad-datetime":
        return None
    start, end = bounds
    if start.date() == end.date():
        return f"{start:%Y-%m-%d %H:%M} to {end:%H:%M}"
    return f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M}"


def check_period(text: str, now: datetime | None = None) -> tuple[bool, str]:
    """Return (is_valid, message_for_the_user)."""
    now = now or datetime.now()
    bounds = _period_bounds(text, now)
    if bounds == "bad-datetime":
        return False, "That date or time doesn't exist. " + PERIOD_HINT
    if not bounds:
        return False, PERIOD_HINT
    start, end = bounds
    if start < now:
        return False, "That time is in the past. Please choose a future date and time."
    if end <= start:
        return False, "The end time must be after the start time."
    return True, ""

def looks_valid(field: str, value: str) -> bool:
    v = value.strip()
    if field in ("name", "surname"):
        return (0 < len(v) <= 40 and len(v.split()) <= 3
                and not any(ch.isdigit() or ch in "?!@" for ch in v))
    if field == "car_number":
        return 3 <= len(v) <= 12 and any(ch.isdigit() for ch in v)
    if field == "period":
        return check_period(v)[0]
    return True


FIELD_LABELS = {
    "name": "first name",
    "surname": "surname",
    "car_number": "car number plate",
    "period": "parking period",
}


def _ask_for_missing(draft: Reservation, missing: list[str], accepted: bool) -> str:
    """Prompt for what's still needed, confirming anything just captured.

    The user can answer several fields in one message, so when more than one is
    missing we list them all (while still spelling out the period format).
    """
    prefix = ""
    if accepted:
        got = [f for f in ("name", "surname", "car_number", "period")
               if getattr(draft, f)]
        prefix = "Got it so far: " + ", ".join(
            f"{FIELD_LABELS[f]} ({getattr(draft, f)})" for f in got) + ".\n\n"

    if len(missing) == 1:
        return prefix + FIELD_QUESTIONS[missing[0]]

    wanted = ", ".join(FIELD_LABELS[f] for f in missing)
    reply = (prefix + f"I still need your {wanted}. "
             "You can give them all in one message.")
    if "period" in missing:
        reply += "\n\n" + FIELD_QUESTIONS["period"]
    return reply


def format_summary(draft: Reservation, reference: str | None = None) -> str:
    lines = [f"- **Reference number:** {reference}"] if reference else []
    lines += [
        f"- **Name:** {draft.name} {draft.surname}",
        f"- **Car number:** {draft.car_number}",
        f"- **Period:** {draft.period}",
    ]
    return "\n".join(lines)


CONFIRM_HINT = ("Reply **yes** to send it to the administrator for approval, tell me what "
                "to change (e.g. \"change the car to XY-123\"), or say **cancel**.")


def _confirmation_prompt(draft: Reservation, changed: bool = False) -> str:
    head = "Updated. Here is your reservation:" if changed else "Please check your reservation:"
    return f"{head}\n\n{format_summary(draft)}\n\n{CONFIRM_HINT}"


def _reminder(draft: Reservation) -> str:
    """What to tack onto a side answer so the user knows the booking is still open."""
    missing = draft.missing()
    if missing:
        return "(We're still booking: " + FIELD_QUESTIONS[missing[0]] + ")"
    return "(Your reservation is waiting for your confirmation. " + CONFIRM_HINT + ")"


# A reply made only of these words is a plain yes / no to the summary. Anything
# else ("no, change the car to XY123") goes through the LLM as a correction.
YES_WORDS = {"yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed",
             "correct", "submit", "send", "ahead", "good", "perfect", "right", "great"}
YES_FILLER = {"go", "looks", "all", "that's", "thats", "is", "it", "please", "thanks",
              "thank", "you", "that"}
NO_WORDS = {"no", "n", "nope", "nah", "cancel", "stop", "nevermind", "never", "forget", "abort"}
NO_FILLER = {"mind", "it", "that", "this", "the", "booking", "reservation", "please",
             "thanks", "thank", "you"}


def _is_only(msg: str, strong: set, filler: set) -> bool:
    words = re.sub(r"[^a-z' ]", " ", msg.lower()).split()
    return (bool(words) and any(w in strong for w in words)
            and all(w in strong or w in filler for w in words))


def is_yes(msg: str) -> bool:
    return _is_only(msg, YES_WORDS, YES_FILLER)


def is_no(msg: str) -> bool:
    return _is_only(msg, NO_WORDS, NO_FILLER)


STATUS_TEXT = {
    "pending": "is waiting for the administrator's approval.",
    "approved": "has been **approved** and confirmed. See you at CityPark!",
    "refused": "was **refused** by the administrator.",
    "save_failed": ("was approved, but we couldn't record it (it may overlap another "
                    "booking for this car). Please contact the front desk."),
}
STATUS_NEEDS_BOTH = (
    "To check a reservation I need both its reference number (e.g. CP-7K3F9Q) and the "
    "car number plate it was booked for. Please send them together, e.g. "
    "\"status of CP-7K3F9Q for car AB-1234\".")


def _status_reply(reference: str | None, car_number: str | None) -> str:
    if not reference or not car_number:
        return STATUS_NEEDS_BOTH
    try:
        req = check_status(reference, car_number)
    except Exception:
        return "Sorry, I can't reach the reservation system right now. Please try again shortly."
    if not req:
        # Same answer whether the reference or the car is wrong, so nothing leaks.
        return ("I couldn't find a reservation matching that reference number and car "
                "number plate. Please check both and try again.")
    res = Reservation(**req["details"]["reservation"])
    text = STATUS_TEXT.get(req["status"], f"has status: {req['status']}.")
    return f"Reservation **{req['reference']}** {text}\n\n{format_summary(res, req['reference'])}"


def _period_expired(period: str, now: datetime | None = None) -> bool:
    bounds = parse_period(period)
    return not bounds or bounds[0] < (now or datetime.now())


def chat_turn(user_msg: str, draft: Reservation, collecting: bool):
    """
    One step of the conversation.
    Returns (reply, updated_draft, collecting, ready_for_admin).

    Still collecting with a complete draft means the summary has been shown and
    we're waiting for the user to confirm, correct or cancel it. ready_for_admin
    is only True once they have said yes.
    """
    if is_malicious(user_msg):
        return "Sorry, I can't help with that request.", draft, collecting, False

    confirming = collecting and not draft.missing()
    if confirming and is_yes(user_msg):
        # The summary may have sat for a while; don't submit a start time that's gone by.
        if _period_expired(draft.period):
            draft = draft.model_copy(update={"period": None})
            return ("That start time has already passed. " + FIELD_QUESTIONS["period"],
                    draft, True, False)
        return "Thank you! Sending your reservation to the administrator...", draft, False, True
    if confirming and is_no(user_msg):
        return ("No problem, I've cancelled that reservation. Is there anything else "
                "I can help with?"), Reservation(), False, False

    # Ask the LLM: what does the user want, and did they give booking details?
    turn = llm.with_structured_output(Turn).invoke(
        "Classify the intent of the message as 'reserve' (wants to book, is giving booking "
        "details, or is changing details of the booking being confirmed), 'status' (wants to "
        "check the status of an existing reservation), 'info' (asks a question about the "
        "parking) or 'other'. Also extract any of: name, surname, car_number, period, "
        "reference (a reservation reference number like CP-7K3F9Q; never put it in "
        "car_number). Leave a field null if it is not in the message.\n"
        f"Currently collecting booking details: {collecting}\n"
        f"Waiting for the user to confirm a complete booking: {confirming}\n"
        f"Message: {user_msg}"
    )

    # Status check. Handled before any draft update so the car number given
    # here isn't mistaken for the booking in progress. Mid-booking we trust
    # only the intent, since a car plate could look like a reference.
    reference = parse_reference(user_msg) or parse_reference(turn.reference or "")
    if turn.intent == "status" or (reference and not collecting):
        car = turn.car_number if not parse_reference(turn.car_number or "") else None
        reply = _status_reply(reference, car)
        if collecting:
            reply += "\n\n" + _reminder(draft)
        return reply, draft, collecting, False

    # Only accept LLM-extracted values for fields that are still empty, or any
    # field while confirming (the user is correcting the summary).
    # The LLM may return several at once, so a single message can fill many
    # fields ("I'm John Smith, plate ABC123, tomorrow 9am-5pm").
    still_missing = draft.missing()
    updates = {k: v for k, v in turn.model_dump().items()
               if k in Reservation.model_fields and v
               and (k in still_missing or (confirming and v != getattr(draft, k)))}

    # When we just asked for a specific field and the user is answering only
    # that one field, their own words are more reliable than the LLM's
    # extraction (it may trim the date, for example). But if the LLM pulled
    # several fields out of this message, it's a multi-field answer and we must
    # not clobber it by stuffing the whole message into a single field.
    single_field_answer = len(updates) <= 1
    if collecting and still_missing and turn.intent != "info" and single_field_answer:
        asked = still_missing[0]
        if asked in ("period", "car_number"):
            updates[asked] = user_msg.strip().rstrip(".,;")

    # Fallback: mid-booking, nothing usable extracted, not a question
    # -> treat the message as the answer to the field we just asked for
    if collecting and not updates and turn.intent != "info" and still_missing:
        updates = {still_missing[0]: user_msg.strip()}

    # Drop answers that don't look valid (e.g. a whole sentence as a surname)
    updates_before_filter = dict(updates)
    rejected = [k for k, v in updates.items() if not looks_valid(k, v)]
    updates = {k: v for k, v in updates.items() if k not in rejected}
    if "period" in updates:
        canon = canonicalize_period(updates["period"])
        if canon:
            updates["period"] = canon
    draft = draft.model_copy(update=updates)
    if rejected:
        if rejected[0] == "period":
            _, msg = check_period(updates_before_filter["period"])
            return msg, draft, True, False
        label = rejected[0].replace("_", " ")
        return (f"Sorry, that doesn't look like a valid {label}. "
                f"{FIELD_QUESTIONS[rejected[0]]}"), draft, True, False
    
    wants_booking = turn.intent == "reserve" or (collecting and turn.intent != "info")
    if wants_booking:
        missing = draft.missing()
        if missing:
            return _ask_for_missing(draft, missing, accepted=bool(updates)), draft, True, False
        return _confirmation_prompt(draft, changed=confirming and bool(updates)), draft, True, False

    # Otherwise answer an info question with RAG
    docs = get_retriever().invoke(user_msg)
    static = redact("\n\n".join(d.page_content for d in docs))
    reply = llm.invoke(ANSWER_PROMPT.format(
        static=static, dynamic=get_dynamic_context(), question=user_msg)).content
    reply = redact(reply)
    if collecting:
        reply += "\n\n" + _reminder(draft)
    return reply, draft, collecting, False