import streamlit as st
from src.graph import run_turn
from src.rag.chatbot import Reservation

st.set_page_config(page_title="CityPark Assistant", page_icon="🅿️")
st.title("🅿️ CityPark Parking Assistant")
st.caption("Ask about prices, hours and location, book a space, or check a reservation's status.")

WELCOME = ("Hi! I can answer questions about CityPark, help you book a space, or check "
           "the status of a reservation (just give me its reference number and car plate).")


def reset():
    st.session_state.messages = [{"role": "assistant", "content": WELCOME}]
    st.session_state.draft = Reservation()
    st.session_state.collecting = False


if "messages" not in st.session_state:
    reset()
if "references" not in st.session_state:
    st.session_state.references = []  # survives "Start over" on purpose

# Sidebar: show what has been collected so far
with st.sidebar:
    st.header("Your booking")
    d = st.session_state.draft
    st.write(f"**Name:** {d.name or '-'}")
    st.write(f"**Surname:** {d.surname or '-'}")
    st.write(f"**Car number:** {d.car_number or '-'}")
    st.write(f"**Period:** {d.period or '-'}")
    if st.session_state.collecting and not d.missing():
        st.info("Waiting for your confirmation.")
    st.button("Start over", on_click=reset)

    if st.session_state.references:
        st.header("Submitted this session")
        for ref, car in st.session_state.references:
            st.write(f"**{ref}** ({car})")

# Show the conversation so far
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# Handle a new message
if prompt := st.chat_input("Type your message..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            out = run_turn(prompt, st.session_state.draft, st.session_state.collecting)
        st.markdown(out["reply"])

    if out.get("reference"):
        st.session_state.references.append((out["reference"], st.session_state.draft.car_number))
    st.session_state.draft = out["draft"]
    st.session_state.collecting = out["collecting"]
    st.session_state.messages.append({"role": "assistant", "content": out["reply"]})
    st.rerun()
