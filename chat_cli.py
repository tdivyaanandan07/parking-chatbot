from src.rag.chatbot import chat_turn, Reservation, format_summary

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
        from src.admin.agent import submit_for_approval
        try:
            ref = submit_for_approval(draft.model_dump())
        except Exception:
            print("Bot: Sorry, I couldn't reach the administrator. Reply 'yes' to try again.")
            collecting = True
            continue
        print("Bot: Sent to the administrator for approval.\n" + format_summary(draft, ref))
        print(f"Bot: Ask me for the status any time with {ref} and your car number.")
        draft, collecting = Reservation(), False
