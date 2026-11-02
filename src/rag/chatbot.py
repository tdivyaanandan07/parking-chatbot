from typing import Optional, Literal
import re
from pydantic import BaseModel
from src.config import llm
from src.db.sql_db import get_dynamic_context
from src.rag.vector_store import load_retriever
from src.guardrails.filters import redact, is_malicious

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
    intent: Literal["info", "reserve", "other"]
    name: Optional[str] = None
    surname: Optional[str] = None
    car_number: Optional[str] = None
    period: Optional[str] = None


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

def looks_valid(field: str, value: str) -> bool:
    v = value.strip()
    if field in ("name", "surname"):
        return (0 < len(v) <= 40 and len(v.split()) <= 3
                and not any(ch.isdigit() or ch in "?!@" for ch in v))
    if field == "car_number":
        return 3 <= len(v) <= 12 and any(ch.isdigit() for ch in v)
    if field == "period":
        return bool(re.search(r"\d{4}-\d{2}-\d{2}", v)) and len(v) >= 12
    return True


def chat_turn(user_msg: str, draft: Reservation, collecting: bool):
    """
    One step of the conversation.
    Returns (reply, updated_draft, collecting, ready_for_admin).
    """
    if is_malicious(user_msg):
        return "Sorry, I can't help with that request.", draft, collecting, False

    # Ask the LLM: what does the user want, and did they give booking details?
    turn = llm.with_structured_output(Turn).invoke(
        "Classify the intent of the message as 'reserve' (wants to book or is giving booking "
        "details), 'info' (asks a question about the parking) or 'other'. Also extract any of: "
        "name, surname, car_number, period. Leave a field null if it is not in the message.\n"
        f"Currently collecting booking details: {collecting}\n"
        f"Message: {user_msg}"
    )

        # Only accept LLM-extracted values for fields that are still empty
        # Only accept LLM-extracted values for fields that are still empty
    still_missing = draft.missing()
    updates = {k: v for k, v in turn.model_dump().items()
               if k != "intent" and v and k in still_missing}

    # When we just asked for a specific field, the user's own words are more
    # reliable than the LLM's extraction (it may trim the date, for example).
    if collecting and still_missing and turn.intent != "info":
        asked = still_missing[0]
        if asked in ("period", "car_number"):
            updates[asked] = user_msg.strip().rstrip(".,;")

    # Fallback: mid-booking, nothing usable extracted, not a question
    # -> treat the message as the answer to the field we just asked for
    if collecting and not updates and turn.intent != "info" and still_missing:
        updates = {still_missing[0]: user_msg.strip()}

    # Drop answers that don't look valid (e.g. a whole sentence as a surname)
    rejected = [k for k, v in updates.items() if not looks_valid(k, v)]
    updates = {k: v for k, v in updates.items() if k not in rejected}

    draft = draft.model_copy(update=updates)
    if rejected:
        label = rejected[0].replace("_", " ")
        return (f"Sorry, that doesn't look like a valid {label}. "
                f"{FIELD_QUESTIONS[rejected[0]]}"), draft, True, False
    
    wants_booking = turn.intent == "reserve" or (collecting and turn.intent != "info")
    if wants_booking:
        missing = draft.missing()
        if missing:
            return FIELD_QUESTIONS[missing[0]], draft, True, False
        return "Thank you! I'm sending your request to the administrator for approval...", draft, False, True

    # Otherwise answer an info question with RAG
    docs = get_retriever().invoke(user_msg)
    static = redact("\n\n".join(d.page_content for d in docs))
    reply = llm.invoke(ANSWER_PROMPT.format(
        static=static, dynamic=get_dynamic_context(), question=user_msg)).content
    reply = redact(reply)
    if collecting:
        reply += "\n\n(We're still booking: " + FIELD_QUESTIONS[draft.missing()[0]] + ")"
    return reply, draft, collecting, False