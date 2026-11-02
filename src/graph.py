from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

from src.rag.chatbot import chat_turn, Reservation
from src.admin.agent import request_approval
from src.mcp_client import save_via_mcp


class State(TypedDict):
    user_msg: str
    draft: Reservation
    collecting: bool
    reply: str
    ready: bool
    decision: Optional[str]


def chat_node(s: State):
    """Agent 1: RAG chatbot. Answers questions and collects booking details."""
    reply, draft, collecting, ready = chat_turn(s["user_msg"], s["draft"], s["collecting"])
    return {"reply": reply, "draft": draft, "collecting": collecting,
            "ready": ready, "decision": None}


def admin_node(s: State):
    """Agent 2: asks the human administrator and waits."""
    decision = request_approval(s["draft"].model_dump())
    return {"decision": decision}


def record_node(s: State):
    """MCP server writes the approved booking to the file."""
    d = s["draft"]
    result = save_via_mcp(f"{d.name} {d.surname}", d.car_number, d.period)
    ok = "OK" in result
    reply = ("Your reservation is approved and saved!" if ok
             else "Approved, but saving failed. Please contact the front desk.")
    return {"reply": reply, "draft": Reservation(), "collecting": False, "ready": False}


def refused_node(s: State):
    if s["decision"] == "refused":
        reply = "Sorry, the administrator refused this reservation."
    else:
        reply = "The administrator did not respond in time. Please try again later."
    return {"reply": reply, "draft": Reservation(), "collecting": False, "ready": False}


def after_chat(s: State):
    return "admin" if s["ready"] else END


def after_admin(s: State):
    return "record" if s["decision"] == "approved" else "refused"


g = StateGraph(State)
g.add_node("chat", chat_node)
g.add_node("admin", admin_node)
g.add_node("record", record_node)
g.add_node("refused", refused_node)

g.set_entry_point("chat")
g.add_conditional_edges("chat", after_chat, {"admin": "admin", END: END})
g.add_conditional_edges("admin", after_admin, {"record": "record", "refused": "refused"})
g.add_edge("record", END)
g.add_edge("refused", END)

app = g.compile()