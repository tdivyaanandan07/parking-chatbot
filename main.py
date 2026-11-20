from src.graph import run_turn
from src.rag.chatbot import Reservation

state = {"draft": Reservation(), "collecting": False}
print("Parking bot ready! Type 'quit' to exit.")

while True:
    msg = input("\nYou: ")
    if msg.strip().lower() == "quit":
        break
    out = run_turn(msg, state["draft"], state["collecting"])
    state = {"draft": out["draft"], "collecting": out["collecting"]}
    print("Bot:", out["reply"])
