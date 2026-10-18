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
from alerts import latest_completed_session, read_events, read_rules
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

    def test_journal_filters_update_metrics_table_and_empty_state(self):
        history = demo_history("NVDA")
        history.index = history.index.tz_localize("America/New_York")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"INFINITY_DATA_DIR": directory}), patch("yfinance.Ticker.history", return_value=history):
            database = Path(directory) / "forecast_journal.sqlite3"
            old_source = history.loc[:"2026-07-02"]
            record_forecast(database, "NVDA", old_source, SimpleNamespace(upward_score=.7, model_name="Random forest"), .6, "2026-07-03T12:00:00Z")
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE forecasts SET model_revision='older'")
            record_forecast(database, "NVDA", history.iloc[:-1], SimpleNamespace(upward_score=.7, model_name="Random forest"), .6, history.index[-1].normalize() + pd.Timedelta(hours=9))
            app = AppTest.from_file(APP, default_timeout=30).run()
            by_label(app.text_input, "Stock symbol").set_value("NVDA")
            by_label(app.radio, "Data source").set_value("Live")
            by_label(app.button, "Analyze stock →").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(by_label(app.metric, "Scored forecasts").value, "2")
            self.assertTrue(any("95% Wilson" in item.value for item in app.caption))
            by_label(app.selectbox, "Model version").set_value("older").run()
            self.assertFalse(app.exception)
            self.assertEqual(by_label(app.metric, "Scored forecasts").value, "1")
            self.assertEqual(len(app.dataframe[-1].value), 1)
            by_label(app.selectbox, "Performance window").set_value("Last 30 days").run()
            self.assertFalse(app.exception)
            self.assertTrue(any("No saved forecasts match" in item.value for item in app.info))

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

    def test_daily_alert_lifecycle_deduplication_and_history_preservation(self):
        history = demo_history("AMZN")
        history.index = pd.bdate_range(end=latest_completed_session(), periods=len(history), tz="America/New_York")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"INFINITY_DATA_DIR": directory}), patch("yfinance.Ticker.history", return_value=history):
            database = Path(directory) / "alerts.sqlite3"
            app = AppTest.from_file(APP, default_timeout=30).run()
            self.assertFalse(database.exists())
            self.assertFalse(any(button.label == "Create daily alert" for button in app.button))
            by_label(app.text_input, "Stock symbol").set_value("AMZN")
            by_label(app.radio, "Data source").set_value("Live")
            by_label(app.button, "Analyze stock →").click().run()
            self.assertFalse(database.exists())
            by_label(app.number_input, "Alert threshold").set_value(.0001)
            by_label(app.button, "Create daily alert").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(read_rules(database, "AMZN")), 1)
            self.assertEqual(len(read_events(database, "AMZN")), 1)
            self.assertTrue(any("Daily alert saved" in item.value for item in app.success))
            by_label(app.button, "↻ Refresh data").click().run()
            self.assertEqual(len(read_events(database, "AMZN")), 1)
            by_label(app.button, "Pause").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(read_rules(database, "AMZN")[0]["enabled"], 0)
            by_label(app.button, "Resume").click().run()
            self.assertEqual(read_rules(database, "AMZN")[0]["enabled"], 1)
            by_label(app.button, "Remove").click().run()
            self.assertFalse(app.exception)
            self.assertFalse(read_rules(database, "AMZN"))
            self.assertEqual(len(read_events(database, "AMZN")), 1)

    def test_atr_alert_threshold_converts_percent_to_ratio(self):
        history = demo_history("SPY")
        history.index = pd.bdate_range(end=latest_completed_session(), periods=len(history), tz="America/New_York")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"INFINITY_DATA_DIR": directory}), patch("yfinance.Ticker.history", return_value=history):
            app = AppTest.from_file(APP, default_timeout=30).run()
            by_label(app.text_input, "Stock symbol").set_value("SPY")
            by_label(app.radio, "Data source").set_value("Live")
            by_label(app.button, "Analyze stock →").click().run()
            by_label(app.selectbox, "Alert metric").set_value("ATR_pct").run()
            by_label(app.number_input, "Alert threshold").set_value(3.)
            by_label(app.button, "Create daily alert").click().run()
            self.assertFalse(app.exception)
            rule = read_rules(Path(directory) / "alerts.sqlite3", "SPY")[0]
            self.assertEqual(rule["metric"], "ATR_pct")
            self.assertAlmostEqual(rule["threshold"], .03)

    def test_daily_alert_storage_failure_keeps_analysis_available(self):
        history = demo_history("XOM")
        history.index = pd.bdate_range(end=latest_completed_session(), periods=len(history), tz="America/New_York")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"INFINITY_DATA_DIR": directory}), patch("yfinance.Ticker.history", return_value=history), patch("alerts_view.save_rule", side_effect=sqlite3.OperationalError("Private path")):
            app = AppTest.from_file(APP, default_timeout=30).run()
            by_label(app.text_input, "Stock symbol").set_value("XOM")
            by_label(app.radio, "Data source").set_value("Live")
            by_label(app.button, "Analyze stock →").click().run()
            by_label(app.button, "Create daily alert").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Daily alerts are unavailable" in item.value for item in app.warning))
            self.assertTrue(app.metric)
            self.assertFalse(any("Private path" in item.value for item in app.warning))
