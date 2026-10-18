from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from alerts import (check_alerts, evaluate_rule, latest_completed_session,
                    read_events, read_rules, remove_rule, save_rule, set_enabled)


def history(closes=(98., 101.), sessions=("2026-07-01", "2026-07-02")):
    return pd.DataFrame({"Close": closes, "RSI": [65., 75.], "Volume_ratio": [1., 2.], "ATR_pct": [.02, .04]},
                        index=pd.to_datetime(list(sessions)).tz_localize("America/New_York"))


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "alerts.sqlite3"
        self.now = "2026-07-03T12:00:00Z"

    def save(self, metric="Close", comparison="above", threshold=100., style="condition", symbol="AAPL"):
        return save_rule(self.database, symbol, metric, comparison, threshold, style, self.now)

    def test_reading_and_checking_do_not_create_a_database(self):
        self.assertEqual(read_rules(self.database, "AAPL"), [])
        self.assertTrue(read_events(self.database, "AAPL").empty)
        self.assertEqual(check_alerts(self.database, "AAPL", history(), self.now), ([], 0))
        self.assertFalse(self.database.exists())

    def test_invalid_thresholds_and_rules_cannot_be_persisted(self):
        invalid = [("Close", "above", 0., "condition"), ("RSI", "above", 101., "condition"),
                   ("RSI", "below", -1., "condition"), ("Close", "above", float("nan"), "condition"),
                   ("Close", "above", float("inf"), "condition"), ("Unknown", "above", 1., "condition"),
                   ("Close", "sideways", 100., "condition"), ("Close", "above", 100., "future")]
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(ValueError):
                save_rule(self.database, "AAPL", *args, now=self.now)
        self.assertFalse(self.database.exists())

    def test_thresholds_include_equality_for_all_supported_indicators(self):
        for metric, threshold in [("Close", 101.), ("RSI", 75.), ("Volume_ratio", 2.), ("ATR_pct", .04)]:
            with self.subTest(metric=metric):
                identifier, created = self.save(metric=metric, threshold=threshold)
                self.assertTrue(created)
                rule = next(rule for rule in read_rules(self.database, "AAPL") if rule["id"] == identifier)
                self.assertEqual(evaluate_rule(rule, history(), self.now)["status"], "Matched")

    def test_crossing_requires_transition_and_records_previous_value(self):
        self.save(style="crossing")
        _, new = check_alerts(self.database, "AAPL", history(), self.now)
        self.assertEqual(new, 1)
        event = read_events(self.database, "AAPL").iloc[0]
        self.assertEqual(event.observed_value, 101.)
        self.assertEqual(event.previous_value, 98.)
        rule = read_rules(self.database, "AAPL")[0]
        self.assertEqual(evaluate_rule(rule, history((100., 101.)), self.now)["status"], "Waiting")
        self.assertEqual(evaluate_rule(rule, history((105., 106.)), self.now)["status"], "Waiting")

    def test_downward_crossing_and_missing_previous_session(self):
        self.save(comparison="below", style="crossing")
        rule = read_rules(self.database, "AAPL")[0]
        self.assertEqual(evaluate_rule(rule, history((102., 100.)), self.now)["status"], "Matched")
        missing = history(sessions=("2026-06-30", "2026-07-02"))
        self.assertEqual(evaluate_rule(rule, missing, self.now)["status"], "Previous session unavailable")
        self.assertEqual(evaluate_rule(rule, history().iloc[[-1]], self.now)["status"], "Previous session unavailable")

    def test_duplicate_saves_preserve_paused_state_and_original_rule(self):
        identifier, _ = self.save()
        set_enabled(self.database, identifier, False)
        duplicate, created = self.save()
        self.assertFalse(created)
        self.assertEqual(identifier, duplicate)
        self.assertEqual(read_rules(self.database, "AAPL")[0]["enabled"], 0)
        self.assertEqual(check_alerts(self.database, "AAPL", history(), self.now)[1], 0)
        set_enabled(self.database, identifier, True)
        self.assertEqual(check_alerts(self.database, "AAPL", history(), self.now)[1], 1)

    def test_refresh_and_concurrent_checks_cannot_duplicate_or_rewrite_events(self):
        self.save()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: check_alerts(self.database, "AAPL", history(), self.now)[1], range(4)))
        self.assertEqual(sum(results), 1)
        before = read_events(self.database, "AAPL")
        self.assertEqual(check_alerts(self.database, "AAPL", history((98., 120.)), self.now)[1], 0)
        pd.testing.assert_frame_equal(before, read_events(self.database, "AAPL"))
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)

    def test_new_session_can_record_condition_without_backfilling_old_sessions(self):
        self.save()
        self.assertEqual(check_alerts(self.database, "AAPL", history(), self.now)[1], 1)
        later = history((101., 103.), ("2026-07-02", "2026-07-06"))
        self.assertEqual(check_alerts(self.database, "AAPL", later, "2026-07-07T12:00:00Z")[1], 1)
        self.assertEqual(list(read_events(self.database, "AAPL").source_session), ["2026-07-06", "2026-07-02"])

    def test_stale_today_and_future_candles_cannot_trigger(self):
        self.save()
        for now in ["2026-07-02T22:00:00Z", "2026-07-01T12:00:00Z", "2026-07-07T12:00:00Z"]:
            with self.subTest(now=now):
                self.assertEqual(check_alerts(self.database, "AAPL", history(), now)[1], 0)
        self.assertTrue(read_events(self.database, "AAPL").empty)

    def test_calendar_freshness_handles_holidays_weekends_and_daylight_saving(self):
        for now, expected in [("2026-07-06T13:00:00Z", "2026-07-02"),
                              ("2026-07-05T16:00:00Z", "2026-07-02"),
                              ("2026-01-20T14:00:00Z", "2026-01-16"),
                              ("2026-07-07T00:30:00Z", "2026-07-02")]:
            with self.subTest(now=now):
                self.assertEqual(latest_completed_session(now), expected)

    def test_unknown_market_and_missing_indicators_do_not_trigger(self):
        self.save(metric="RSI", threshold=70)
        rule = read_rules(self.database, "AAPL")[0]
        bad = history()
        bad.loc[bad.index[-1], "RSI"] = float("nan")
        self.assertEqual(evaluate_rule(rule, bad, self.now)["status"], "Indicator unavailable")
        self.assertEqual(evaluate_rule(rule, history().drop(columns="RSI"), self.now)["status"], "Indicator unavailable")
        other_market = history().tz_convert("UTC")
        self.assertEqual(check_alerts(self.database, "AAPL", other_market, self.now)[1], 0)

    def test_removal_retains_history_and_does_not_affect_other_symbols(self):
        identifier, _ = self.save()
        self.save(symbol="MSFT")
        check_alerts(self.database, "AAPL", history(), self.now)
        remove_rule(self.database, identifier)
        self.assertFalse(read_rules(self.database, "AAPL"))
        self.assertEqual(len(read_events(self.database, "AAPL")), 1)
        self.assertEqual(len(read_rules(self.database, "MSFT")), 1)
        self.assertTrue(read_events(self.database, "MSFT").empty)

    def test_rule_limit_is_enforced_after_duplicate_lookup(self):
        for value in range(20):
            self.save(threshold=value + 1)
        self.assertFalse(self.save(threshold=1)[1])
        with self.assertRaises(ValueError):
            self.save(threshold=21)
