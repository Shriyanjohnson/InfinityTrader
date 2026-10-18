"""Account, tester help, and privacy controls for the public-beta candidate."""
import io
import ipaddress
import json
import os
import shutil
import secrets
import sqlite3
import time
import tempfile
import zipfile

import streamlit as st

import accounts
from settings import VERSION, account_directory, data_root, development, free_beta


def _client():
    # Trust only the deployment's isolated reverse proxy, which overwrites this header.
    if os.environ.get("INFINITY_TRUSTED_PROXY") == "1":
        try:
            return str(ipaddress.ip_address(st.context.headers.get("X-Real-IP", "")))
        except ValueError:
            pass
    return st.context.ip_address or "unknown"


def refresh_principal():
    user = accounts.principal(st.session_state.get("_auth_token"))
    st.session_state["_principal"] = user or {}
    return user


def _reset(token=None, recovery=None):
    st.session_state.clear()
    if token:
        st.session_state["_auth_token"] = token
    if recovery:
        st.session_state["_recovery_code"] = recovery
    st.session_state.page = "Account"


def render_account(user):
    st.title("Your beta account")
    st.caption("Use a unique username and password. Sessions last up to 12 hours and end when you sign out. Save your recovery code: email password resets are not available.")
    if user:
        st.success(f"Signed in as {user['username']}.")
        if st.session_state.get("_recovery_code"):
            st.warning("Save this recovery code privately. It can reset your password. It is displayed once and replaces any previous code.")
            st.code(st.session_state["_recovery_code"], language=None)
            if st.button("I saved my recovery code"):
                del st.session_state["_recovery_code"]
                st.rerun()
        st.write("Your watchlist, forecast journal, and alerts are private to this account.")
        st.caption("Free beta access is enabled." if free_beta() else "Demo is free. Live research and background checks use confirmed $5 / 30-day Bitcoin access.")
        if st.button("Sign out"):
            accounts.logout(st.session_state["_auth_token"])
            _reset()
            st.rerun()
        with st.expander("Export or delete my account"):
            if st.button("Prepare my data export"):
                st.download_button("Download my beta data", export_account(user), file_name="infinitytrader_beta_data.zip", mime="application/zip")
            st.caption("Deletion removes account credentials, watchlists, feedback, alerts, and forecasts. Pseudonymous Bitcoin transaction records may be retained for payment reconciliation. Backups expire under the operator's retention policy.")
            with st.form("delete_account"):
                password = st.text_input("Confirm password", type="password", max_chars=128)
                confirm = st.checkbox("Permanently delete my account and research data")
                delete = st.form_submit_button("Delete my account")
            if delete:
                try:
                    if not confirm:
                        raise ValueError("Confirm deletion first.")
                    from worker import owner_lock
                    with owner_lock(user["id"]):
                        accounts.verify_password(user["id"], password)
                        shutil.rmtree(account_directory(user["id"]), ignore_errors=False) if account_directory(user["id"]).exists() else None
                        accounts.delete_account(user["id"], password)
                    _reset()
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
        return
    sign_in, sign_up, recovery = st.tabs(["Sign in", "Create account", "Recover account"])
    with sign_in, st.form("login"):
        name = st.text_input("Username", max_chars=32)
        password = st.text_input("Password", type="password", max_chars=128)
        submit = st.form_submit_button("Sign in")
    if submit:
        try:
            token = accounts.login(name, password, _client())
            _reset(token)
            st.rerun()
        except ValueError as error:
            st.error(str(error))
    with sign_up, st.form("register"):
        username = st.text_input("Choose username", max_chars=32)
        new_password = st.text_input("Choose password", type="password", max_chars=128)
        confirmation = st.text_input("Repeat password", type="password", max_chars=128)
        consent = st.checkbox("I am 18 or older and accept the beta terms and privacy notice in Beta guide & feedback.")
        register = st.form_submit_button("Create beta account")
    if register:
        try:
            if new_password != confirmation:
                raise ValueError("Passwords must match.")
            _, code = accounts.register(username, new_password, consent, _client())
            token = accounts.login(username, new_password, _client())
            _reset(token, code)
            st.rerun()
        except ValueError as error:
            st.error(str(error))
    with recovery, st.form("recover"):
        name = st.text_input("Account username", max_chars=32)
        code = st.text_input("Recovery code", type="password", max_chars=128)
        password = st.text_input("New password", type="password", max_chars=128)
        reset = st.form_submit_button("Reset password")
    if reset:
        try:
            replacement = accounts.recover(name, code, password, _client())
            token = accounts.login(name, password, _client())
            _reset(token, replacement)
            st.rerun()
        except ValueError as error:
            st.error(str(error))


def export_account(user):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("export-reference.txt", secrets.token_hex(32))
        archive.writestr("account.json", json.dumps({"username": user["username"], "watchlist": json.loads(user["watchlist"])}))
        with accounts.database() as connection:
            feedback = [dict(row) for row in connection.execute("SELECT category,message,created_at FROM feedback WHERE owner=?", (user["id"],))]
        archive.writestr("feedback.json", json.dumps(feedback))
        directory = account_directory(user["id"])
        for path in sorted(directory.glob("*.sqlite3")) if directory.exists() else []:
            with tempfile.TemporaryDirectory() as temporary:
                backup = os.path.join(temporary, "snapshot.sqlite3")
                source, target = sqlite3.connect(path), sqlite3.connect(backup)
                try:
                    source.backup(target)
                finally:
                    source.close()
                    target.close()
                with open(backup, "rb") as stream:
                    archive.writestr(path.name, stream.read())
    return output.getvalue()


def render_guide(user):
    st.title("Beta guide & feedback")
    st.caption(f"InfinityTrader {VERSION} · Public-beta candidate")
    st.write("1. Explore Demo without an account. 2. Create an account and save your recovery code. 3. Add watchlist symbols, save Live forecasts, and create daily alert rules. 4. Return after later sessions to review outcomes and send feedback.")
    st.write("Daily data excludes today's entire New York session. Alerts check completed daily conditions, not intraday prices. With the worker running, matches appear in your private Daily alerts history even while you are away. No trades, emails, or push messages are sent.")
    with st.expander("Beta terms", expanded=False):
        st.write("This is experimental stock-research software for adults. Features and availability may change; data and forecasts can be wrong. It provides educational research, not personalized investment advice or brokerage services. No predictive edge or profit is promised. Do not submit sensitive information in feedback or rely on alerts for execution. Do not abuse the service or share credentials. Beta access may be withdrawn. Paid purchases, when enabled, are $5 for 30 days; renewal requires another confirmed Bitcoin payment. Bitcoin transfers are irreversible; contact the operator for payment disputes or refunds.")
    with st.expander("Privacy notice", expanded=False):
        st.write("We store your username, Argon2id password/recovery hashes, consent version, watchlist, forecasts, alert rules/history, and feedback on the app server. Session tokens are stored as hashes. Abuse controls store salted hashes of network addresses and attempt times; requests and worker cycles purge these after 24 hours. No email is required for an account, and no advertising trackers are used. Market providers receive symbol requests and server network information. Optional news requests go to NewsAPI. If checkout is enabled, public Bitcoin transaction identifiers and account-linked entitlement records are retained for reconciliation. Export and delete research data in Account; the operator must expire backups under the published retention policy. Do not submit passwords, wallet secrets, or personal financial information.")
    support = os.environ.get("INFINITY_SUPPORT_EMAIL", "")
    st.caption(f"Support/privacy contact: {support}" if support else "Operator support contact is not configured. Public deployment must configure it.")
    if user:
        status_path = data_root() / "worker-status.json"
        try:
            status = json.loads(status_path.read_text())
            fresh = time.time() - status["checked_at"] < 2 * max(60, int(os.environ.get("INFINITY_WORKER_INTERVAL", "900"))) + 60
            if not status.get("live_enabled"):
                st.info("Background worker is waiting for the operator to enable licensed live data.")
            elif fresh:
                st.caption(f"Background worker checked in recently · {status.get('errors', 0)} provider/storage errors in its last cycle.")
            else:
                st.warning("Background worker heartbeat is stale. On-demand Live analysis still checks your current symbol.")
        except (OSError, ValueError, KeyError, TypeError):
            st.info("Background worker status is not available yet. The operator should start the full service supervisor.")
        with st.form("beta_feedback"):
            category = st.selectbox("Feedback type", ["Bug", "Idea", "Data issue"])
            message = st.text_area("Tell us what happened", max_chars=3000)
            submit = st.form_submit_button("Send beta feedback")
        if submit:
            try:
                accounts.save_feedback(user["id"], category, message)
                st.success("Feedback saved for the operator. No email was sent.")
            except ValueError as error:
                st.error(str(error))
    else:
        st.info("Sign in to send feedback. Demo stays available without an account.")
