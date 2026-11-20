"""LangGraph orchestration of the whole pipeline:

    chat -> submit -> admin_approval (pauses) -> record -> END

Each customer message is its own graph run (thread). Most runs end after `chat`.
A confirmed booking goes on to `submit`, then pauses at `admin_approval` with
LangGraph's interrupt(): the customer gets the reference number at once and
keeps chatting. The admin inbox resumes that thread with the decision, and an
approved booking is written to the file by the `record` node through MCP.

Paused runs are kept in a SQLite checkpoint store, so the chat process and the
admin API process (and restarts of either) share them.
"""
import sqlite3
import uuid
from pathlib import Path
from typing import TypedDict, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, END
from langgraph.types import Command, interrupt

from src.rag.chatbot import chat_turn, Reservation, format_summary
from src.admin.agent import submit_for_approval
from src.admin.recording import record_approved
from src.db import requests_db

CHECKPOINT_DB = Path("data/checkpoints.db")


class State(TypedDict, total=False):
    user_msg: str
    draft: Reservation
    collecting: bool
    reply: str
    ready: bool
    reference: Optional[str]
    approved: Optional[bool]


def chat_node(s: State):
    """Agent 1: RAG chatbot. Answers questions, collects and confirms booking details,
    and checks the status of existing reservations."""
    reply, draft, collecting, ready = chat_turn(s["user_msg"], s["draft"], s["collecting"])
    return {"reply": reply, "draft": draft, "collecting": collecting,
            "ready": ready, "reference": None}


def submit_node(s: State, config: RunnableConfig = None):
    """Agent 2: sends the confirmed booking to the administrator's inbox, tagged with
    this thread so the admin's decision can resume it at admin_approval."""
    d = s["draft"]
    thread_id = ((config or {}).get("configurable") or {}).get("thread_id")
    try:
        ref = submit_for_approval(d.model_dump(), thread_id)
    except Exception:
        # Keep the draft and stay in confirmation, so "yes" simply retries.
        return {"reply": ("Sorry, I couldn't reach the administrator just now. Your details "
                          "are kept; reply **yes** to try again or **cancel**."),
                "collecting": True, "ready": False}
    reply = (
        "Your reservation has been sent to the administrator for approval.\n\n"
        f"{format_summary(d, ref)}\n\n"
        f"Please keep your reference number **{ref}**. To check the status later, just ask "
        f"me and give the reference number together with your car number plate, e.g. "
        f"\"status of {ref} for car {d.car_number}\".\n\n"
        "Is there anything else I can help with? You can make another reservation too."
    )
    return {"reply": reply, "draft": Reservation(), "collecting": False,
            "ready": False, "reference": ref}


def approval_node(s: State):
    """Human in the loop: pause until the administrator decides. The run is saved
    here and the value passed to Command(resume=...) comes back from interrupt()."""
    decision = interrupt({"reference": s["reference"]})
    approved = bool(decision.get("approved"))
    if not approved:
        requests_db.set_status(s["reference"], "refused")
    return {"approved": approved}


def record_node(s: State):
    """Data recording: write the approved booking to the file via the MCP server."""
    record_approved(s["reference"])
    return {}


def after_chat(s: State):
    return "submit" if s["ready"] else END


def after_submit(s: State):
    return "admin_approval" if s.get("reference") else END


def after_approval(s: State):
    return "record" if s["approved"] else END


def build_graph(checkpointer=None):
    g = StateGraph(State)
    g.add_node("chat", chat_node)
    g.add_node("submit", submit_node)
    g.add_node("admin_approval", approval_node)
    g.add_node("record", record_node)

    g.set_entry_point("chat")
    g.add_conditional_edges("chat", after_chat, {"submit": "submit", END: END})
    g.add_conditional_edges("submit", after_submit,
                            {"admin_approval": "admin_approval", END: END})
    g.add_conditional_edges("admin_approval", after_approval, {"record": "record", END: END})
    g.add_edge("record", END)
    return g.compile(checkpointer=checkpointer)


def sqlite_checkpointer(path: Path = CHECKPOINT_DB) -> SqliteSaver:
    path.parent.mkdir(exist_ok=True)
    # The draft is stored in checkpoints; allow loading it back explicitly.
    serde = JsonPlusSerializer(allowed_msgpack_modules=[("src.rag.chatbot", "Reservation")])
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False), serde=serde)


app = build_graph(sqlite_checkpointer())


def run_turn(user_msg: str, draft: Reservation, collecting: bool) -> dict:
    """Run one customer message through the graph, on a thread of its own so a
    booking left waiting for the administrator never blocks the conversation."""
    return app.invoke(
        {"user_msg": user_msg, "draft": draft, "collecting": collecting,
         "reply": "", "ready": False, "reference": None},
        {"configurable": {"thread_id": str(uuid.uuid4())}})


def resume_with_decision(thread_id: str, approved: bool) -> bool:
    """Hand the administrator's decision to the run paused at admin_approval.
    Returns False if that thread isn't waiting there."""
    config = {"configurable": {"thread_id": thread_id}}
    if "admin_approval" not in app.get_state(config).next:
        return False
    app.invoke(Command(resume={"approved": approved}), config)
    return True
