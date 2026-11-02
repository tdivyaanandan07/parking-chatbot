import streamlit as st
from src.graph import app as graph
from src.rag.chatbot import Reservation

st.set_page_config(page_title="CityPark Assistant", page_icon="🅿️")
st.title("🅿️ CityPark Parking Assistant")
st.caption("Ask about prices, hours and location, or book a space.")

WELCOME = "Hi! I can answer questions about CityPark or help you book a space."


def reset():
    st.session_state.messages = [{"role": "assistant", "content": WELCOME}]
    st.session_state.draft = Reservation()
    st.session_state.collecting = False


if "messages" not in st.session_state:
    reset()

# Sidebar: show what has been collected so far
with st.sidebar:
    st.header("Your booking")
    d = st.session_state.draft
    st.write(f"**Name:** {d.name or '-'}")
    st.write(f"**Surname:** {d.surname or '-'}")
    st.write(f"**Car number:** {d.car_number or '-'}")
    st.write(f"**Period:** {d.period or '-'}")
    st.button("Start over", on_click=reset)

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
        with st.spinner("Working... (a booking waits here for the administrator)"):
            out = graph.invoke({
                "user_msg": prompt,
                "draft": st.session_state.draft,
                "collecting": st.session_state.collecting,
                "reply": "", "ready": False, "decision": None,
            })
        st.markdown(out["reply"])

    st.session_state.draft = out["draft"]
    st.session_state.collecting = out["collecting"]
    st.session_state.messages.append({"role": "assistant", "content": out["reply"]})
    st.rerun()