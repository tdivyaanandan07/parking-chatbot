from src.rag.chatbot import chat_turn, Reservation

draft = Reservation()
collecting = False
print("Parking bot ready! Type 'quit' to exit.")

while True:
    msg = input("\nYou: ")
    if msg.strip().lower() == "quit":
        break
    reply, draft, collecting, ready = chat_turn(msg, draft, collecting)
    print("Bot:", reply)
    if ready:
        from src.admin.agent import request_approval
        decision = request_approval(draft.model_dump())
        if decision == "approved":
            from src.mcp_client import save_via_mcp
            save_via_mcp(f"{draft.name} {draft.surname}", draft.car_number, draft.period)
            print("Bot: Your reservation is approved and saved!")
        elif decision == "refused":
            print("Bot: Sorry, the administrator refused this reservation.")
        else:
            print("Bot: The administrator did not respond in time. Please try again later.")
        draft, collecting = Reservation(), False