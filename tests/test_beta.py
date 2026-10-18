from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import pandas as pd
from streamlit.testing.v1 import AppTest

import accounts
from alerts import save_rule, read_events, latest_completed_session
from analytics import demo_history
from beta_ui import export_account
from beta_ui import _client
from checkout import btc_quote
from manage import backup, preflight
from market_data import get_history
from settings import account_directory, workspace_directory, checkout_enabled
from exports import csv_bytes
from worker import run_once

APP = str(Path(__file__).resolve().parents[1] / "main.py")
PASSWORD = "fixture beta password 2026"


def by_label(elements, label):
    return next(item for item in elements if item.label == label)


def prices():
    data = demo_history("AAPL")
    data.index = pd.bdate_range(end=latest_completed_session(), periods=len(data), tz="America/New_York")
    return data


class BetaTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.dict(os.environ, {"INFINITY_MODE": "beta", "INFINITY_DATA_DIR": self.directory,
            "INFINITY_FREE_BETA": "1", "INFINITY_CHECKOUT_ENABLED": "0", "INFINITY_LIVE_DATA_ENABLED": "0",
            "INFINITY_DATA_LICENSE_ACK": "0", "INFINITY_PUBLIC_URL": "", "INFINITY_SUPPORT_EMAIL": ""}))

    def user(self, name="alice", client="test-client"):
        owner, code = accounts.register(name, PASSWORD, True, client=client)
        token = accounts.login(name, PASSWORD, client=client)
        return owner, code, token, accounts.principal(token)

    def test_password_and_session_are_hashed_and_sessions_expire_and_revoke(self):
        owner, code = accounts.register("alice", PASSWORD, True, now=1000)
        token = accounts.login("alice", PASSWORD, now=1001)
        self.assertEqual(accounts.principal(token, now=1002)["id"], owner)
        self.assertIsNone(accounts.principal(token, now=1001 + 43200))
        with accounts.database() as connection:
            row = connection.execute("SELECT * FROM users").fetchone()
            self.assertTrue(row["password_hash"].startswith("$argon2id$"))
            self.assertNotIn(PASSWORD, row["password_hash"])
            self.assertNotEqual(connection.execute("SELECT token_hash FROM sessions").fetchone()[0], token)
        accounts.logout(token)
        self.assertIsNone(accounts.principal(token, now=1002))

    def test_registration_validation_and_username_casefold(self):
        for name, password, consent in [("../bad", PASSWORD, True), ("ok_user", "short", True), ("ok_user", PASSWORD, False)]:
            with self.assertRaises(ValueError):
                accounts.register(name, password, consent)
        self.user("Alice")
        with self.assertRaises(ValueError):
            accounts.register("ALICE", PASSWORD, True)
        self.assertIsNotNone(accounts.principal(accounts.login("ALICE", PASSWORD)))

    def test_unknown_user_and_wrong_password_share_error_and_rate_limits_persist(self):
        self.user()
        errors = []
        for username in ["alice", "nobody"]:
            try:
                accounts.login(username, "wrong password")
            except ValueError as error:
                errors.append(str(error))
        self.assertEqual(errors[0], errors[1])
        for _ in range(12):
            try:
                accounts.login("nobody", "wrong password")
            except ValueError:
                pass
        with self.assertRaisesRegex(ValueError, "Too many"):
            accounts.login("nobody", PASSWORD)

    def test_recovery_code_is_one_time_and_revokes_all_sessions(self):
        owner, code, token, user = self.user()
        token2 = accounts.login("alice", PASSWORD)
        replacement = accounts.recover("alice", code, "replacement beta password")
        self.assertNotEqual(code, replacement)
        self.assertIsNone(accounts.principal(token))
        self.assertIsNone(accounts.principal(token2))
        with self.assertRaises(ValueError):
            accounts.recover("alice", code, PASSWORD)
        self.assertEqual(accounts.principal(accounts.login("alice", "replacement beta password"))["id"], owner)

    def test_account_storage_and_exports_do_not_include_other_users_or_password_hashes(self):
        alice, _, _, user = self.user()
        bob, _, _, _ = self.user("bob", "other-client")
        save_rule(account_directory(alice) / "alerts.sqlite3", "AAPL", "Close", "above", 1.)
        save_rule(account_directory(bob) / "alerts.sqlite3", "MSFT", "Close", "above", 2.)
        accounts.save_feedback(bob, "Bug", "Private Bob feedback stays private.")
        accounts.save_feedback(alice, "Idea", "Private Alice feedback belongs to Alice.")
        archive = zipfile.ZipFile(io.BytesIO(export_account(user)))
        self.assertNotIn("accounts.sqlite3", archive.namelist())
        self.assertIn("alerts.sqlite3", archive.namelist())
        self.assertNotIn(b"Bob", archive.read("feedback.json"))
        self.assertNotIn(b"argon2", archive.read("account.json"))
        with self.assertRaises(ValueError):
            account_directory("../../outside")

    def test_watchlists_are_private_and_limited(self):
        alice, _, _, _ = self.user()
        bob, _, _, _ = self.user("bob", "other-client")
        accounts.save_watchlist(alice, ["TSLA", "TSLA"])
        with accounts.database() as connection:
            self.assertEqual(json.loads(connection.execute("SELECT watchlist FROM users WHERE id=?", (alice,)).fetchone()[0]), ["TSLA"])
            self.assertIn("AAPL", json.loads(connection.execute("SELECT watchlist FROM users WHERE id=?", (bob,)).fetchone()[0]))
        with self.assertRaises(ValueError):
            accounts.save_watchlist(alice, ["../bad"])

    def test_deletion_invalidates_sessions_and_requires_password(self):
        owner, _, token, user = self.user()
        with self.assertRaises(ValueError):
            accounts.delete_account(owner, "wrong password")
        self.assertIsNotNone(accounts.principal(token))
        accounts.delete_account(owner, PASSWORD)
        self.assertIsNone(accounts.principal(token))

    def test_beta_defaults_block_charging_and_unlicensed_provider_requests(self):
        self.assertFalse(checkout_enabled())
        with patch("requests.get") as request, self.assertRaises(ValueError):
            get_history("AAPL")
        request.assert_not_called()
        os.environ["INFINITY_CHECKOUT_ENABLED"] = "1"
        self.assertFalse(checkout_enabled())

    def test_licensed_provider_maps_adjusted_history_and_does_not_leak_key_on_error(self):
        os.environ.update(INFINITY_LIVE_DATA_ENABLED="1", INFINITY_DATA_LICENSE_ACK="1", TWELVEDATA_API_KEY="fixture-not-a-real-key")
        body = {"meta": {"exchange_timezone": "America/New_York"}, "values": [
            {"datetime": "2026-07-02", "open": "100", "high": "102", "low": "99", "close": "101", "volume": "10000"}]}
        response = Mock()
        response.json.return_value = body
        with patch("requests.get", return_value=response) as request:
            result = get_history("AAPL")
        self.assertEqual(str(result.index.tz), "America/New_York")
        self.assertEqual(result.Close.iloc[0], "101")
        self.assertEqual(request.call_args.kwargs["params"]["adjust"], "all")
        response.json.return_value = {"status": "error", "message": "fixture-not-a-real-key"}
        with patch("requests.get", return_value=response), self.assertRaisesRegex(ValueError, "Daily prices are unavailable"):
            get_history("AAPL")

    def test_quote_fetch_is_server_side_and_rejects_wrong_currency(self):
        response = Mock()
        response.json.return_value = {"data": {"currency": "USD", "amount": "100000"}}
        with patch("requests.get", return_value=response):
            self.assertEqual(btc_quote(), 100000)
        response.json.return_value = {"data": {"currency": "EUR", "amount": "100000"}}
        with patch("requests.get", return_value=response), self.assertRaises(ValueError):
            btc_quote()

    def test_worker_checks_private_accounts_and_deduplicates_provider_fetches(self):
        alice, _, _, _ = self.user()
        bob, _, _, _ = self.user("bob", "other-client")
        for owner in (alice, bob):
            accounts.save_watchlist(owner, ["AAPL"])
            save_rule(account_directory(owner) / "alerts.sqlite3", "AAPL", "Close", "above", .001)
        os.environ.update(INFINITY_LIVE_DATA_ENABLED="1", INFINITY_DATA_LICENSE_ACK="1")
        loader = Mock(return_value=prices())
        state = run_once(loader)
        self.assertEqual(state["matches"], 2)
        loader.assert_called_once_with("AAPL")
        self.assertEqual(len(read_events(account_directory(alice) / "alerts.sqlite3", "AAPL")), 1)
        self.assertEqual(len(read_events(account_directory(bob) / "alerts.sqlite3", "AAPL")), 1)
        self.assertEqual(run_once(loader)["matches"], 0)
        self.assertTrue((Path(self.directory) / "worker-status.json").exists())

    def test_preflight_refuses_placeholders_and_backups_preserve_account_database(self):
        self.user()
        self.assertFalse(preflight(public=True)["ready"])
        with tempfile.TemporaryDirectory() as destination:
            folder = backup(destination)
            with sqlite3.connect(folder / "accounts.sqlite3") as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("SELECT count(*) FROM users").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            backup(Path(self.directory) / "bad-backup")

    def test_public_guest_cannot_open_live_or_inherit_a_forged_principal(self):
        app = AppTest.from_file(APP, default_timeout=45).run()
        self.assertFalse(app.exception)
        app.session_state["_principal"] = {"id": "a" * 32, "username": "forged"}
        by_label(app.radio, "Data source").set_value("Live")
        by_label(app.button, "Analyze stock →").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Sign in through Account" in item.value for item in app.info))
        self.assertEqual(app.session_state["_principal"], {})

    def test_account_signup_recovery_display_signout_and_feedback(self):
        app = AppTest.from_file(APP, default_timeout=45).run()
        by_label(app.radio, "Explore").set_value("Account").run()
        by_label(app.text_input, "Choose username").set_value("browser_tester")
        by_label(app.text_input, "Choose password").set_value(PASSWORD)
        by_label(app.text_input, "Repeat password").set_value(PASSWORD)
        app.checkbox[0].check()
        by_label(app.button, "Create beta account").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.session_state["_recovery_code"])
        self.assertEqual(app.session_state["_principal"]["username"], "browser_tester")
        by_label(app.button, "I saved my recovery code").click().run()
        by_label(app.radio, "Explore").set_value("Beta guide & feedback").run()
        by_label(app.text_area, "Tell us what happened").set_value("The private beta feedback path works correctly.")
        by_label(app.button, "Send beta feedback").click().run()
        self.assertTrue(app.success)
        by_label(app.radio, "Explore").set_value("Account").run()
        by_label(app.button, "Sign out").click().run()
        self.assertFalse(app.exception)
        self.assertNotIn("_auth_token", app.session_state)

    def test_background_payment_discovery_confirms_only_the_invoice_owner_once(self):
        from test_billing import Chain, NOW, TXID
        from billing import create_invoice, has_access, _database
        from reconcile import reconcile_once
        alice, _, _, _ = self.user()
        bob, _, _, _ = self.user("bob", "other-client")
        os.environ.update(INFINITY_FREE_BETA="0", INFINITY_CHECKOUT_ENABLED="1")
        chain = Chain()
        chain.address_transactions = Mock(side_effect=lambda _: [chain.transaction(TXID)])
        invoice = create_invoice(Path(self.directory) / "billing.sqlite3", alice, 50000, chain, now=NOW)
        result = reconcile_once(chain, now=NOW + 60)
        self.assertEqual(result["paid"], 0)
        self.assertFalse(has_access(Path(self.directory) / "billing.sqlite3", alice, now=NOW + 60))
        chain.confirm(timestamp=NOW + 1800)
        self.assertEqual(reconcile_once(chain, now=NOW + 1900)["paid"], 1)
        self.assertTrue(has_access(Path(self.directory) / "billing.sqlite3", alice, now=NOW + 1901))
        self.assertFalse(has_access(Path(self.directory) / "billing.sqlite3", bob, now=NOW + 1901))
        with _database(Path(self.directory) / "billing.sqlite3") as connection:
            original_expiry = connection.execute("SELECT access_until FROM invoices WHERE id=?", (invoice["id"],)).fetchone()[0]
        self.assertEqual(reconcile_once(chain, now=NOW + 2000)["paid"], 0)
        with _database(Path(self.directory) / "billing.sqlite3") as connection:
            self.assertEqual(connection.execute("SELECT access_until FROM invoices WHERE id=?", (invoice["id"],)).fetchone()[0], original_expiry)

    def test_paid_worker_does_not_check_an_unentitled_account(self):
        owner, _, _, _ = self.user()
        save_rule(account_directory(owner) / "alerts.sqlite3", "AAPL", "Close", "above", .001)
        os.environ.update(INFINITY_FREE_BETA="0", INFINITY_LIVE_DATA_ENABLED="1", INFINITY_DATA_LICENSE_ACK="1")
        loader = Mock(return_value=prices())
        self.assertEqual(run_once(loader)["matches"], 0)
        loader.assert_not_called()

    def test_worker_continues_other_symbols_after_provider_failure(self):
        owner, _, _, _ = self.user()
        accounts.save_watchlist(owner, ["AAPL", "MSFT"])
        save_rule(account_directory(owner) / "alerts.sqlite3", "MSFT", "Close", "above", .001)
        os.environ.update(INFINITY_LIVE_DATA_ENABLED="1", INFINITY_DATA_LICENSE_ACK="1")
        loader = Mock(side_effect=[RuntimeError("Provider unavailable"), prices()])
        result = run_once(loader)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["matches"], 1)

    def test_public_config_preflight_accepts_complete_operator_settings_without_network(self):
        os.environ.update(INFINITY_PUBLIC_URL="https://beta.my-stock-tool.test", INFINITY_SUPPORT_EMAIL="operator@my-stock-tool.test",
            INFINITY_LIVE_DATA_ENABLED="1", INFINITY_DATA_LICENSE_ACK="1", TWELVEDATA_API_KEY="fixture",
            INFINITY_MARKET_PROVIDER="twelvedata", INFINITY_OPERATOR_TERMS_ACK="1")
        self.assertTrue(preflight(public=True)["ready"])
        os.environ["INFINITY_MODE"] = "development"
        self.assertFalse(preflight(public=True)["ready"])

    def test_database_backed_resource_budget_and_feedback_rate_limit(self):
        owner, _, _, _ = self.user()
        accounts.budget("fixture", 1, now=1000)
        with self.assertRaises(ValueError):
            accounts.budget("fixture", 1, now=1001)
        accounts.budget("fixture", 1, now=1061)
        for _ in range(10):
            accounts.save_feedback(owner, "Bug", "A sufficiently long fixture report.", now=1000)
        with self.assertRaises(ValueError):
            accounts.save_feedback(owner, "Bug", "An additional fixture report.", now=1001)

    def test_billing_checkout_ui_uses_signed_in_owner_and_server_quote(self):
        from test_billing import Chain, TXID
        from billing import has_access, _database
        import time
        owner, _, token, _ = self.user()
        os.environ.update(INFINITY_FREE_BETA="0", INFINITY_CHECKOUT_ENABLED="1")
        chain = Chain()
        with patch("checkout.btc_quote", return_value=50000), patch("checkout.BlockstreamClient", return_value=chain):
            app = AppTest.from_file(APP, default_timeout=45)
            app.session_state["_auth_token"] = token
            app.session_state["page"] = "Account"
            app.run()
            by_label(app.button, "Create $5 Bitcoin invoice").click().run()
            self.assertFalse(app.exception)
            with _database(Path(self.directory) / "billing.sqlite3") as connection:
                invoice = dict(connection.execute("SELECT * FROM invoices").fetchone())
            self.assertEqual(invoice["owner"], owner)
            self.assertEqual(invoice["amount_sats"], 10000)
            chain.confirm(timestamp=invoice["created_at"])
            by_label(app.text_input, "Transaction ID").set_value(TXID)
            by_label(app.button, "Verify blockchain payment").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(has_access(Path(self.directory) / "billing.sqlite3", owner))

    def test_proxy_client_headers_are_ignored_without_explicit_trusted_deployment(self):
        context = Mock(ip_address="172.18.0.2", headers={"X-Real-IP": "192.0.2.15"})
        with patch("beta_ui.st.context", context):
            os.environ.pop("INFINITY_TRUSTED_PROXY", None)
            self.assertEqual(_client(), "172.18.0.2")
            os.environ["INFINITY_TRUSTED_PROXY"] = "1"
            self.assertEqual(_client(), "192.0.2.15")

    def test_revoked_session_clears_private_watchlist_and_ui_state(self):
        owner, _, token, _ = self.user()
        accounts.save_watchlist(owner, ["PRIVATE"])
        app = AppTest.from_file(APP, default_timeout=45)
        app.session_state["_auth_token"] = token
        app.run()
        self.assertEqual(app.session_state["watchlist"], ["PRIVATE"])
        accounts.logout(token)
        app.run()
        self.assertFalse(app.exception)
        self.assertNotIn("_auth_token", app.session_state)
        self.assertNotIn("PRIVATE", app.session_state["watchlist"])
        self.assertEqual(app.session_state["page"], "Account")

    def test_private_exports_are_unique_without_changing_original_records(self):
        frame = pd.DataFrame({"symbol": ["AAPL"], "score": [.5]})
        first, second = csv_bytes(frame), csv_bytes(frame)
        self.assertNotEqual(first, second)
        self.assertNotIn("export_id", frame.columns)
        exported = pd.read_csv(io.BytesIO(first))
        self.assertEqual(exported.symbol.iloc[0], "AAPL")
        self.assertEqual(len(exported.export_id.iloc[0]), 64)

    def test_paid_mode_live_gate_cannot_be_bypassed_by_a_signed_in_unpaid_user(self):
        _, _, token, _ = self.user()
        os.environ.update(INFINITY_FREE_BETA="0", INFINITY_LIVE_DATA_ENABLED="1", INFINITY_DATA_LICENSE_ACK="1")
        with patch("market_data.get_history") as loader:
            app = AppTest.from_file(APP, default_timeout=45)
            app.session_state["_auth_token"] = token
            app.run()
            by_label(app.radio, "Data source").set_value("Live")
            by_label(app.button, "Analyze stock →").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Live access requires a confirmed" in item.value for item in app.info))
            loader.assert_not_called()
