import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from analytics import demo_history
from forecast_journal import record_forecast

APP = str(Path(__file__).resolve().parents[1] / "main.py")


def by_label(elements, label):
    return next(element for element in elements if element.label == label)


class AppTests(unittest.TestCase):
    def test_demo_render_and_interactions_require_no_network(self):
        with patch("yfinance.Ticker.history", side_effect=RuntimeError("Network must not be used")) as history:
            app = AppTest.from_file(APP, default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.title[0].value, "AAPL · Apple")
            self.assertTrue(any("simulated" in message.value for message in app.info))
            by_label(app.radio, "Chart range").set_value("1Y")
            by_label(app.selectbox, "Chart style").set_value("Line")
            app.run()
            self.assertFalse(app.exception)
            by_label(app.button, "NVDA  ·  NVIDIA").click().run()
            self.assertEqual(app.title[0].value, "NVDA · NVIDIA")
            self.assertFalse(app.exception)
            history.assert_not_called()

    def test_invalid_symbol_keeps_last_valid_analysis(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        by_label(app.text_input, "Stock symbol").set_value("<invalid>")
        by_label(app.button, "Analyze stock →").click().run()
        self.assertEqual(app.title[0].value, "AAPL · Apple")
        self.assertTrue(app.error)
        self.assertFalse(app.exception)

    def test_live_error_is_safe_and_demo_recovery_works(self):
        with patch("yfinance.Ticker.history", side_effect=RuntimeError("Sensitive provider details")):
            app = AppTest.from_file(APP, default_timeout=30).run()
            by_label(app.radio, "Data source").set_value("Live")
            by_label(app.button, "Analyze stock →").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertNotIn("Sensitive", app.error[0].value)
            self.assertFalse(app.metric)
            by_label(app.button, "Open demo workspace").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.metric)
            self.assertTrue(any("simulated" in item.value for item in app.info))

    def test_live_success_is_labeled_and_watchlist_can_change(self):
        with patch("yfinance.Ticker.history", return_value=demo_history("AMD")):
            app = AppTest.from_file(APP, default_timeout=30).run()
            by_label(app.text_input, "Stock symbol").set_value("AMD")
            by_label(app.radio, "Data source").set_value("Live")
            by_label(app.button, "Analyze stock →").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.title[0].value, "AMD · Stock analysis")
            self.assertTrue(any("YAHOO · DAILY DATA" in item.value for item in app.markdown))
            by_label(app.button, "+ Add current stock").click().run()
            self.assertIn("AMD", app.session_state.watchlist)
            by_label(app.button, "Remove current stock").click().run()
            self.assertNotIn("AMD", app.session_state.watchlist)

    def test_live_forecast_can_be_saved_once_without_changing_analysis(self):
        history = demo_history("TSLA")
        history.index = history.index.tz_localize("America/New_York")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"INFINITY_DATA_DIR": directory}), patch("yfinance.Ticker.history", return_value=history):
            app = AppTest.from_file(APP, default_timeout=30).run()
            self.assertFalse((Path(directory) / "forecast_journal.sqlite3").exists())
            by_label(app.text_input, "Stock symbol").set_value("TSLA")
            by_label(app.radio, "Data source").set_value("Live")
            by_label(app.button, "Analyze stock →").click().run()
            self.assertFalse(app.exception)
            self.assertFalse((Path(directory) / "forecast_journal.sqlite3").exists())
            by_label(app.button, "Save this forecast").click().run()
            self.assertTrue(any("Forecast saved" in item.value for item in app.success))
            self.assertFalse(app.exception)
            self.assertEqual(app.title[0].value, "TSLA · Tesla")
            self.assertTrue(any("awaiting a later completed session" in item.value for item in app.caption))
            by_label(app.button, "Save this forecast").click().run()
            self.assertTrue(any("first snapshot is preserved" in item.value for item in app.info))
            with sqlite3.connect(Path(directory) / "forecast_journal.sqlite3") as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM forecasts").fetchone()[0], 1)

    def test_journal_storage_failure_keeps_dashboard_available(self):
        history = demo_history("GOOG")
        history.index = history.index.tz_localize("America/New_York")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"INFINITY_DATA_DIR": directory}), patch("yfinance.Ticker.history", return_value=history), patch("journal_view.record_forecast", side_effect=sqlite3.OperationalError("Private path")):
            app = AppTest.from_file(APP, default_timeout=30).run()
            by_label(app.text_input, "Stock symbol").set_value("GOOG")
            by_label(app.radio, "Data source").set_value("Live")
            by_label(app.button, "Analyze stock →").click().run()
            by_label(app.button, "Save this forecast").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.metric)
            self.assertTrue(any("forecast journal is unavailable" in item.value for item in app.warning))
            self.assertFalse(any("Private path" in item.value for item in app.warning))

    def test_later_live_analysis_resolves_snapshot_and_shows_performance(self):
        history = demo_history("MSFT")
        history.index = history.index.tz_localize("America/New_York")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"INFINITY_DATA_DIR": directory}), patch("yfinance.Ticker.history", return_value=history):
            database = Path(directory) / "forecast_journal.sqlite3"
            recorded = history.index[-1].normalize() + pd.Timedelta(hours=9)
            record_forecast(database, "MSFT", history.iloc[:-1], SimpleNamespace(upward_score=.7, model_name="Random forest"), .6, recorded)
            app = AppTest.from_file(APP, default_timeout=30).run()
            by_label(app.text_input, "Stock symbol").set_value("MSFT")
            by_label(app.radio, "Data source").set_value("Live")
            by_label(app.button, "Analyze stock →").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(by_label(app.metric, "Scored forecasts").value, "1")
            self.assertTrue(any("historical-frequency baseline" in item.value for item in app.caption))
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT eligible FROM forecasts").fetchone()[0], 1)

    def test_old_history_is_flagged(self):
        history = demo_history("META")
        history.index = history.index - pd.Timedelta(days=30)
        with patch("yfinance.Ticker.history", return_value=history):
            app = AppTest.from_file(APP, default_timeout=30).run()
            by_label(app.text_input, "Stock symbol").set_value("META")
            by_label(app.radio, "Data source").set_value("Live")
            by_label(app.button, "Analyze stock →").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("calendar days old" in item.value for item in app.warning))

    def test_pricing_and_signup_form_persist_and_workspace_navigation_works(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"INFINITY_DATA_DIR": directory}):
            app = AppTest.from_file(APP, default_timeout=30).run()
            by_label(app.radio, "Explore").set_value("Product & pricing").run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Paid subscriptions are not available" in item.value for item in app.caption))
            by_label(app.text_input, "Email address").set_value("test@example.com")
            by_label(app.button, "Join early access").click().run()
            self.assertTrue(app.error)
            self.assertFalse((Path(directory) / "early_access.sqlite3").exists())
            app.checkbox[0].check()
            by_label(app.button, "Join early access").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.success)
            with sqlite3.connect(Path(directory) / "early_access.sqlite3") as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM signups").fetchone()[0], 1)
            by_label(app.button, "Open free workspace").click().run()
            self.assertEqual(app.title[0].value, "AAPL · Apple")
            self.assertFalse(app.exception)
