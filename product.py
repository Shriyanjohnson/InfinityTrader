from pathlib import Path
import json
import os
import sqlite3

import streamlit as st

from early_access import save_signup

BILLING = json.loads(Path(__file__).with_name("billing_config.json").read_text())


def open_workspace():
    st.session_state.page = "Research workspace"


def render_product_page():
    st.markdown('<div class="eyebrow">INFINITYTRADER · EARLY ACCESS</div>', unsafe_allow_html=True)
    left, right = st.columns([1.6, 1], gap="large")
    with left:
        st.markdown('<div class="hero">Your next move starts<br>with <span>better context.</span></div>', unsafe_allow_html=True)
        st.markdown('<div class="muted">A focused workspace for active traders. Research your watchlist today; help shape price and volatility alerts for Pro.</div>', unsafe_allow_html=True)
        st.write("")
        st.button("Explore the workspace →", type="primary", on_click=open_workspace)
        st.caption("Try the demo immediately. No payment required.")
    with right, st.container(border=True):
        st.markdown("### Research with perspective")
        st.write("**01 · See the full picture**")
        st.caption("Interactive price charts, volume, moving averages, RSI, and volatility.")
        st.write("**02 · Understand the signal**")
        st.caption("Chronological model evaluation and a simple baseline alongside every result.")
        st.write("**03 · Make it your workspace**")
        st.caption("A session watchlist, CSV exports, and optional news headlines.")
    st.divider()
    st.subheader("Start exploring. Help shape what comes next.")
    st.caption("Pro pricing is a proposal for early feedback. Paid subscriptions are not available yet.")
    free, pro = st.columns(2, gap="large")
    with free, st.container(border=True):
        st.markdown('<div class="eyebrow">EXPLORER · AVAILABLE NOW</div>', unsafe_allow_html=True)
        st.markdown("## $0")
        st.write("A place to start your research.")
        st.markdown("- Live and demo stock analysis\n- Interactive charts and technical indicators\n- Session watchlist and CSV export\n- Transparent model validation\n- Daily in-app price and indicator alerts")
        st.button("Open free workspace", on_click=open_workspace, width="stretch")
    with pro, st.container(border=True):
        st.markdown('<div class="eyebrow">PRO · PLANNED FOR LAUNCH</div>', unsafe_allow_html=True)
        st.markdown(f"## ${BILLING['pro_price_usd']} / 30 days")
        st.caption("Pay in Bitcoin. The BTC amount will be quoted at checkout; access starts after 3 blockchain confirmations. Checkout is not available yet.")
        st.write("An alert-focused plan for active traders.")
        st.markdown("- Background price-threshold monitoring\n- Scheduled volatility alerts and delivery\n- Watchlists saved across devices\n- Notification history and delivery controls")
        st.caption("Background monitoring, notification delivery, and account-based Pro features are planned. Current daily in-app rules check when you run analysis.")
    st.write("")
    with st.container(border=True):
        st.subheader("Get the launch update")
        st.caption("Join the early-access list and help shape Pro. No payment or account is created.")
        with st.form("early_access"):
            email = st.text_input("Email address", placeholder="you@example.com", max_chars=254)
            consent = st.checkbox("I agree to receive an email about the InfinityTrader launch.")
            submitted = st.form_submit_button("Join early access", type="primary")
        st.caption("This development version stores your email on this app server. It does not send emails. Contact the operator to remove it; a published privacy policy is required before public launch.")
        if submitted:
            location = os.environ.get("INFINITY_DATA_DIR")
            base = Path(location) if location else Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "infinitytrader"
            try:
                save_signup(email, consent, base / "early_access.sqlite3")
                st.success("You're on the early-access list. No payment has been taken.")
            except ValueError as error:
                st.error(str(error))
            except (OSError, sqlite3.Error):
                st.error("Signup could not be saved. Please try again later.")
    st.markdown('<div class="footer">InfinityTrader · Market research, with context. Educational analysis only; model scores do not guarantee returns.</div>', unsafe_allow_html=True)
