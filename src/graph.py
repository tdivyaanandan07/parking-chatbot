from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

from src.rag.chatbot import chat_turn, Reservation, format_summary
from src.admin.agent import submit_for_approval


class State(TypedDict):
    user_msg: str
    draft: Reservation
    collecting: bool
    reply: str
    ready: bool
    reference: Optional[str]


def chat_node(s: State):
    """Agent 1: RAG chatbot. Answers questions, collects and confirms booking details,
    and checks the status of existing reservations."""
    reply, draft, collecting, ready = chat_turn(s["user_msg"], s["draft"], s["collecting"])
    return {"reply": reply, "draft": draft, "collecting": collecting,
            "ready": ready, "reference": None}


def submit_node(s: State):
    """Agent 2: sends the confirmed booking to the administrator without waiting.
    Approved requests are written to the file by the admin API through MCP."""
    d = s["draft"]
    try:
        ref = submit_for_approval(d.model_dump())
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


def after_chat(s: State):
    return "submit" if s["ready"] else END


g = StateGraph(State)
g.add_node("chat", chat_node)
g.add_node("submit", submit_node)

g.set_entry_point("chat")
g.add_conditional_edges("chat", after_chat, {"submit": "submit", END: END})
g.add_edge("submit", END)

app = g.compile()
