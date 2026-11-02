from src.graph import app
from src.rag.chatbot import Reservation

state = {"draft": Reservation(), "collecting": False}
print("Parking bot ready! Type 'quit' to exit.")

while True:
    msg = input("\nYou: ")
    if msg.strip().lower() == "quit":
        break
    out = app.invoke({
        "user_msg": msg, "draft": state["draft"], "collecting": state["collecting"],
        "reply": "", "ready": False, "decision": None,
    })
    state = {"draft": out["draft"], "collecting": out["collecting"]}
    print("Bot:", out["reply"])