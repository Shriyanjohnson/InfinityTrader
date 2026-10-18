from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest

import pandas as pd

from forecast_journal import (filter_forecasts, performance, performance_trend,
                              read_forecasts, record_forecast, settle_forecasts)
from market_sessions import next_session_info


def prices(sessions=("2026-07-02",), closes=(100,)):
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes,
                         "Volume": 1000}, index=pd.to_datetime(list(sessions)).tz_localize("America/New_York"))


class ForecastJournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "journal.sqlite3"
        self.result = SimpleNamespace(upward_score=.7, model_name="Random forest")

    def record(self, now="2026-07-03T10:00:00Z", data=None, symbol="AAPL"):
        return record_forecast(self.database, symbol, prices() if data is None else data, self.result, .6, now)

    def test_no_implicit_database_creation_when_reading(self):
        self.assertTrue(read_forecasts(self.database, "AAPL").empty)
        settle_forecasts(self.database, "AAPL", prices())
        self.assertFalse(self.database.exists())

    def test_duplicate_snapshot_cannot_overwrite_original_score(self):
        self.assertTrue(self.record())
        self.result.upward_score = .1
        self.assertFalse(self.record(now="2026-07-06T15:00:00Z"))
        record = read_forecasts(self.database, "AAPL").iloc[0]
        self.assertEqual(record.upward_score, .7)
        self.assertEqual(record.recorded_at, "2026-07-03T10:00:00+00:00")
        self.assertEqual(len(record.data_fingerprint), 64)
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)

    def test_concurrent_saves_keep_one_snapshot(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            created = list(pool.map(lambda _: self.record(), range(4)))
        self.assertEqual(sum(created), 1)
        self.assertEqual(len(read_forecasts(self.database, "AAPL")), 1)

    def test_weekend_and_holiday_use_next_observed_session(self):
        self.record(now="2026-07-06T13:29:59Z")
        history = prices(("2026-07-02", "2026-07-06"), (100, 105))
        settle_forecasts(self.database, "AAPL", history, "2026-07-07T12:00:00Z")
        record = read_forecasts(self.database, "AAPL").iloc[0]
        self.assertEqual(record.target_session, "2026-07-06")
        self.assertEqual(record.eligible, 1)
        self.assertEqual(record.outcome, 1)
        self.assertAlmostEqual(record.actual_return, .05)

    def test_exact_open_and_later_snapshots_are_excluded(self):
        for stamp in ["2026-07-06T13:30:00Z", "2026-07-06T19:59:00Z"]:
            with self.subTest(stamp=stamp):
                database = Path(self.directory.name) / f"{stamp[-9:-1].replace(':', '')}.sqlite3"
                record_forecast(database, "AAPL", prices(), self.result, .6, stamp)
                settle_forecasts(database, "AAPL", prices(("2026-07-02", "2026-07-06"), (100, 110)), "2026-07-07T12:00:00Z")
                records = read_forecasts(database, "AAPL")
                self.assertEqual(records.iloc[0].eligible, 0)
                self.assertIsNone(performance(records))

    def test_changing_today_candle_does_not_settle(self):
        self.record()
        settle_forecasts(self.database, "AAPL", prices(("2026-07-02", "2026-07-06"), (100, 110)), "2026-07-06T19:00:00Z")
        self.assertTrue(read_forecasts(self.database, "AAPL").outcome.isna().all())

    def test_pending_or_missing_source_history_does_not_invent_outcome(self):
        self.record()
        settle_forecasts(self.database, "AAPL", prices(), "2026-07-07T12:00:00Z")
        settle_forecasts(self.database, "AAPL", prices(("2026-07-06", "2026-07-07"), (105, 106)), "2026-07-08T12:00:00Z")
        self.assertTrue(read_forecasts(self.database, "AAPL").outcome.isna().all())

    def test_missing_target_session_does_not_grade_a_multiday_return(self):
        self.record()
        # July 6 is a trading day. A missing quote must not turn July 7 into
        # the target of a next-session forecast made from July 2 prices.
        settle_forecasts(self.database, "AAPL", prices(("2026-07-02", "2026-07-07"), (100, 110)), "2026-07-08T12:00:00Z")
        self.assertTrue(read_forecasts(self.database, "AAPL").outcome.isna().all())
        settle_forecasts(self.database, "AAPL", prices(("2026-07-02", "2026-07-06", "2026-07-07"), (100, 99, 110)), "2026-07-08T12:00:00Z")
        resolved = read_forecasts(self.database, "AAPL").iloc[0]
        self.assertEqual(resolved.target_session, "2026-07-06")
        self.assertEqual(resolved.outcome, 0)

    def test_legacy_wrong_session_outcome_is_excluded_without_rewriting_snapshot(self):
        self.record()
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE forecasts SET target_session='2026-07-07', actual_return=.1, outcome=1, eligible=1")
        records = read_forecasts(self.database, "AAPL")
        self.assertFalse(records.iloc[0].session_match)
        self.assertIsNone(performance(records))
        self.assertTrue(performance_trend(records).empty)
        self.assertEqual(records.iloc[0].upward_score, .7)
        self.assertEqual(records.iloc[0].target_session, "2026-07-07")

    def test_weekends_holidays_and_exceptional_closures_are_not_source_sessions(self):
        for day in ["2026-07-03", "2026-07-04", "2025-01-09"]:
            with self.subTest(day=day):
                self.assertIsNone(next_session_info(day))
                with self.assertRaises(ValueError):
                    self.record(data=prices((day,), (100,)), now="2026-07-07T12:00:00Z")
        self.assertEqual(next_session_info("2025-01-08")[0], "2025-01-10")

    def test_confidence_interval_remains_wide_for_one_correct_forecast(self):
        self.record()
        settle_forecasts(self.database, "AAPL", prices(("2026-07-02", "2026-07-06"), (100, 110)), "2026-07-07T12:00:00Z")
        stats = performance(read_forecasts(self.database, "AAPL"))
        self.assertAlmostEqual(stats["accuracy_low"], .20654931437723745)
        self.assertAlmostEqual(stats["accuracy_high"], 1.)

    def test_version_filters_trend_and_metrics_use_the_same_eligible_records(self):
        self.record()
        self.record(data=prices(("2026-07-06",), (110,)), now="2026-07-07T12:00:00Z")
        self.record(data=prices(("2026-07-07",), (100,)), now="2026-07-08T16:00:00Z")
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE forecasts SET model_revision='older' WHERE source_session='2026-07-02'")
        settle_forecasts(self.database, "AAPL", prices(("2026-07-02", "2026-07-06", "2026-07-07", "2026-07-08"), (100, 110, 100, 105)), "2026-07-09T12:00:00Z")
        records = read_forecasts(self.database, "AAPL")
        original = records.copy(deep=True)
        self.assertEqual(performance(records)["count"], 2)
        trend = performance_trend(records)
        self.assertEqual(list(trend.index), ["2026-07-06", "2026-07-07"])
        self.assertEqual(list(trend["Forecast accuracy"]), [1., .5])
        older = filter_forecasts(records, revision="older")
        self.assertEqual(performance(older)["count"], 1)
        self.assertEqual(len(performance_trend(older)), 1)
        recent = filter_forecasts(records, since="2026-07-06")
        self.assertEqual(performance(recent)["count"], 1)
        self.assertEqual(performance(recent)["accuracy"], 0)
        self.assertIsNone(performance(filter_forecasts(records, revision="missing")))
        pd.testing.assert_frame_equal(records, original)

    def test_split_adjustment_uses_consistent_prices_and_resolved_outcome_stays_fixed(self):
        self.record()
        history = prices(("2026-07-02", "2026-07-06"), (50, 51))
        settle_forecasts(self.database, "AAPL", history, "2026-07-07T12:00:00Z")
        first = read_forecasts(self.database, "AAPL")
        self.assertEqual(first.iloc[0].source_close, 100)
        self.assertAlmostEqual(first.iloc[0].actual_return, .02)
        settle_forecasts(self.database, "AAPL", prices(("2026-07-02", "2026-07-06"), (50, 40)), "2026-07-08T12:00:00Z")
        pd.testing.assert_frame_equal(first, read_forecasts(self.database, "AAPL"))

    def test_same_snapshot_baseline_and_accuracy_metrics(self):
        self.record()
        settle_forecasts(self.database, "AAPL", prices(("2026-07-02", "2026-07-06"), (100, 110)), "2026-07-07T12:00:00Z")
        stats = performance(read_forecasts(self.database, "AAPL"))
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["accuracy"], 1)
        self.assertAlmostEqual(stats["brier"], .09)
        self.assertAlmostEqual(stats["baseline_brier"], .16)

    def test_flat_or_falling_outcome_and_symbol_isolation(self):
        self.record(symbol="MSFT")
        self.record()
        settle_forecasts(self.database, "AAPL", prices(("2026-07-02", "2026-07-06"), (100, 100)), "2026-07-07T12:00:00Z")
        self.assertEqual(read_forecasts(self.database, "AAPL").iloc[0].outcome, 0)
        self.assertTrue(read_forecasts(self.database, "MSFT").outcome.isna().all())

    def test_invalid_score_or_unfinished_session_cannot_be_saved(self):
        for value in [float("nan"), 1.1, -.1]:
            self.result.upward_score = value
            with self.assertRaises(ValueError):
                self.record()
        self.result.upward_score = .5
        with self.assertRaises(ValueError):
            self.record(now="2026-07-02T20:00:00Z")
        self.assertFalse(self.database.exists())

    def test_other_exchange_timezone_cannot_be_scored_as_us_regular_open(self):
        history = prices()
        history.index = history.index.tz_convert("UTC")
        with self.assertRaises(ValueError):
            self.record(data=history)

    def test_winter_open_uses_new_york_daylight_saving_rules(self):
        history = prices(("2026-01-16",), (100,))
        self.record(data=history, now="2026-01-20T14:29:59Z")
        settle_forecasts(self.database, "AAPL", prices(("2026-01-16", "2026-01-20"), (100, 101)), "2026-01-21T12:00:00Z")
        self.assertEqual(read_forecasts(self.database, "AAPL").iloc[0].eligible, 1)
