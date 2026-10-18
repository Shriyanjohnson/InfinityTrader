"""Owner-bound checkout UI. Never enables charging implicitly."""
from decimal import Decimal
import time

import requests
import streamlit as st

from billing import (BlockstreamClient, BillingError, BlockchainUnavailable, CONFIG,
                     _database, create_invoice, check_payment, has_access)
from settings import checkout_enabled, data_root, free_beta


def btc_quote():
    try:
        response = requests.get("https://api.coinbase.com/v2/prices/BTC-USD/spot", timeout=10)
        response.raise_for_status()
        body = response.json()["data"]
        value = Decimal(body["amount"])
        if body["currency"] != "USD" or not value.is_finite() or value <= 0:
            raise ValueError
        return value
    except (requests.RequestException, ValueError, KeyError, ArithmeticError):
        raise BillingError("The server could not obtain a fresh BTC/USD quote. No invoice was created.") from None


def render_checkout(user):
    st.subheader("Bitcoin access")
    if free_beta():
        st.info("Free beta access is active. No Bitcoin payment is requested during this test phase. The paid plan remains $5 for 30 days.")
        return
    if not user:
        st.info("Sign in to manage account-bound Bitcoin access.")
        return
    database = data_root() / "billing.sqlite3"
    if has_access(database, user["id"]):
        st.success("Pro access is active for this account.")
    if not checkout_enabled():
        st.info("Real checkout is disabled until the operator completes payment launch checks.")
        return
    st.caption("$5 in Bitcoin for 30 days. Exact amount and purchase timing must match; access starts after three canonical-chain confirmations. Renewals are manual. Transactions are irreversible; review the support/refund terms before sending.")
    try:
        if st.button("Create $5 Bitcoin invoice"):
            import accounts
            accounts.budget(f"invoice:{user['id']}", 3)
            invoice = create_invoice(database, user["id"], btc_quote(), BlockstreamClient())
            st.success("Invoice created for this account.")
        with _database(database) as connection:
            invoices = [dict(row) for row in connection.execute("SELECT * FROM invoices WHERE owner=? ORDER BY created_at DESC LIMIT 5", (user["id"],))]
        for invoice in invoices:
            with st.expander(f"Purchase {invoice['id'][:8]} · {'paid' if invoice['paid_txid'] else 'pending'}"):
                st.write(f"Exact amount: **{Decimal(invoice['amount_sats']) / 100_000_000:.8f} BTC**")
                st.code(invoice["address"], language=None)
                if invoice["paid_txid"]:
                    st.caption("Payment confirmed. Retrying this purchase will not extend access again.")
                    continue
                if int(time.time()) > invoice["expires_at"] and not invoice["observed_txid"]:
                    st.warning("Quote expired. Do not send funds to this invoice; create a new one.")
                else:
                    st.caption("The reconciliation service watches the receiving address during the 15-minute quote window. You can also submit the transaction ID here. Confirmation tracking continues while you are away.")
                with st.form(f"payment_{invoice['id']}"):
                    txid = st.text_input("Transaction ID", max_chars=64)
                    check = st.form_submit_button("Verify blockchain payment")
                if check:
                    result = check_payment(database, invoice["id"], user["id"], txid, BlockstreamClient())
                    st.success("Payment confirmed; 30-day access granted.") if result.status == "paid" else st.info(f"{result.status.replace('_', ' ')} · {result.confirmations} confirmations")
    except (BillingError, BlockchainUnavailable) as error:
        st.error(str(error))
