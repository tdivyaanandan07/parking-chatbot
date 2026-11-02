import requests
import streamlit as st

ADMIN_URL = "http://localhost:8001"

st.set_page_config(page_title="CityPark Admin", page_icon="🛡️")
st.title("🛡️ Administrator: reservation requests")


def decide(rid: str, approved: bool):
    requests.post(f"{ADMIN_URL}/requests/{rid}/decision",
                  json={"approved": approved}, timeout=10)


@st.fragment(run_every=2)  # refreshes this block every 2 seconds
def pending_list():
    try:
        items = requests.get(f"{ADMIN_URL}/requests/pending", timeout=5).json()
    except Exception:
        st.error("Cannot reach the admin inbox. Is uvicorn running on port 8001?")
        return
    if not items:
        st.info("No pending requests.")
        return
    for r in items:
        res = r["details"].get("reservation", {})
        with st.container(border=True):
            st.write(r["details"].get("message", ""))
            st.write(f"**{res.get('name')} {res.get('surname')}** | "
                     f"car **{res.get('car_number')}** | {res.get('period')}")
            c1, c2 = st.columns(2)
            c1.button("✅ Approve", key=f"a-{r['id']}", on_click=decide, args=(r["id"], True))
            c2.button("❌ Refuse", key=f"r-{r['id']}", on_click=decide, args=(r["id"], False))


pending_list()