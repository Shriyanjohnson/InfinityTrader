import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from market_sessions import next_session_info

from analytics import (add_indicators, analyze, chronological_split,
                       demo_history, normalize_history, supervised_data,
                       select_model, walk_forward_splits, completed_history, FEATURES)


def constant_path(step):
    close = 200 + np.arange(150) * step
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                         "Close": close, "Volume": 100},
                        index=pd.bdate_range("2025-01-01", periods=150))


class IndicatorTests(unittest.TestCase):
    def test_today_and_future_candles_are_excluded(self):
        history = constant_path(1)
        day = history.index[-2]
        result = completed_history(history, day.tz_localize("America/New_York") + pd.Timedelta(hours=12))
        pd.testing.assert_frame_equal(result, history.iloc[:-2])
        aware = history.copy()
        aware.index = aware.index.tz_localize("America/New_York")
        result = completed_history(aware, day.tz_localize("America/New_York") + pd.Timedelta(hours=20))
        pd.testing.assert_frame_equal(result, aware.iloc[:-2])

    def test_rsi_monotonic_and_flat_edge_cases(self):
        for step, expected in [(1, 100), (-1, 0), (0, 50)]:
            with self.subTest(step=step):
                data = add_indicators(constant_path(step))
                self.assertAlmostEqual(data.RSI.iloc[-1], expected)
                self.assertTrue(data.RSI.iloc[14:].between(0, 100).all())

    def test_atr_accounts_for_overnight_gap(self):
        source = constant_path(0)
        source.loc[source.index[75]:, ["Open", "High", "Low", "Close"]] += 20
        data = add_indicators(source)
        self.assertGreater(data.ATR.iloc[75], 2)
        self.assertAlmostEqual(data.ATR.iloc[75], (2 * 13 + 21) / 14)

    def test_indicators_do_not_use_future_prices(self):
        source = demo_history("AAPL")
        full = add_indicators(source)
        partial = add_indicators(source.iloc[:150])
        pd.testing.assert_frame_equal(full.iloc[:150], partial)

    def test_obv_signs_and_no_input_mutation(self):
        source = constant_path(1)
        original = source.copy(deep=True)
        data = add_indicators(source)
        self.assertEqual(data.OBV.iloc[0], 0)
        self.assertEqual(data.OBV.iloc[-1], 14900)
        pd.testing.assert_frame_equal(source, original)

    def test_bad_and_short_history_rejected(self):
        for data in [pd.DataFrame(), constant_path(0).iloc[:30], constant_path(0).drop(columns="Volume")]:
            with self.subTest(rows=len(data)), self.assertRaises(ValueError):
                normalize_history(data)

    def test_history_order_and_duplicates(self):
        data = constant_path(1)
        dirty = pd.concat([data, data.iloc[[-1]]]).iloc[::-1]
        clean = normalize_history(dirty)
        pd.testing.assert_frame_equal(clean, data, check_freq=False)


class ModelTests(unittest.TestCase):
    def test_missing_us_session_cannot_create_multiday_training_label(self):
        history = demo_history("AAPL")
        history.index = history.index.tz_localize("America/New_York")
        history = history.loc[[next_session_info(day.date().isoformat()) is not None for day in history.index]]
        source, missing, after_gap = history.index[149:152]
        complete_x, _ = supervised_data(add_indicators(history))
        self.assertIn(source, complete_x.index)
        incomplete_x, _ = supervised_data(add_indicators(history.drop(index=missing)))
        self.assertNotIn(source, incomplete_x.index)
        self.assertIn(after_gap, incomplete_x.index)

    def test_last_unknown_outcome_is_excluded(self):
        data = add_indicators(demo_history("AAPL"))
        features, labels = supervised_data(data)
        self.assertNotIn(data.index[-1], features.index)
        expected = (data.Close.shift(-1).loc[features.index] > data.Close.loc[features.index]).astype(int)
        pd.testing.assert_series_equal(labels, expected)

    def test_training_labels_stop_before_validation(self):
        features, labels = supervised_data(add_indicators(demo_history("MSFT")))
        train_x, test_x, train_y, test_y = chronological_split(features, labels)
        self.assertLess(train_x.index[-1], test_x.index[0])
        last_train_position = features.index.get_loc(train_x.index[-1])
        first_test_position = features.index.get_loc(test_x.index[0])
        self.assertEqual(first_test_position - last_train_position, 2)
        pd.testing.assert_index_equal(train_x.index, train_y.index)
        pd.testing.assert_index_equal(test_x.index, test_y.index)

    def test_single_class_forecasts_do_not_index_missing_class(self):
        for step, expected in [(1, 1), (-1, 0), (0, 0)]:
            with self.subTest(step=step):
                result = analyze(add_indicators(constant_path(step)))
                self.assertEqual(result.upward_score, expected)
                self.assertEqual(result.accuracy, 1)

    def test_result_reports_real_holdout_count_and_baseline(self):
        data = add_indicators(demo_history("AAPL"))
        features, labels = supervised_data(data)
        _, test_x, _, _ = chronological_split(features, labels)
        result = analyze(data)
        self.assertEqual(result.validation_sessions, len(test_x))
        actual, predictions = [], []
        for train, test in walk_forward_splits(features):
            actual.extend(labels.iloc[test])
            predictions.extend(np.full(len(test), labels.iloc[train].mean() >= .5))
        self.assertAlmostEqual(result.baseline, np.mean(np.asarray(actual) == predictions))
        self.assertTrue(0 <= result.upward_score <= 1)
        self.assertTrue(0 <= result.accuracy <= 1)
        self.assertTrue(0 <= result.brier <= 1)
        self.assertTrue(0 <= result.baseline_brier <= 1)

    def test_walk_forward_has_no_overlap_and_purges_each_boundary(self):
        features, _ = supervised_data(add_indicators(demo_history("AAPL")))
        tested = []
        previous_train_size = 0
        for train, test in walk_forward_splits(features):
            self.assertEqual(test[0] - train[-1], 2)
            self.assertGreater(len(train), previous_train_size)
            previous_train_size = len(train)
            tested.extend(test)
        self.assertEqual(tested, list(range(int(len(features) * .8), len(features))))

    def test_model_selection_never_sees_final_evaluation_labels(self):
        data = add_indicators(demo_history("AAPL"))
        features, labels = supervised_data(data)
        train_x, _, train_y, _ = chronological_split(features, labels)
        with patch("analytics.select_model", wraps=select_model) as selection:
            analyze(data)
        selection.assert_called_once()
        pd.testing.assert_frame_equal(selection.call_args.args[0], train_x)
        pd.testing.assert_series_equal(selection.call_args.args[1], train_y)

    def test_selection_is_unchanged_when_later_outcomes_change(self):
        data = add_indicators(demo_history("AAPL"))
        features, labels = supervised_data(data)
        start = int(len(features) * .8)
        changed = labels.copy()
        changed.iloc[start:] = 1 - changed.iloc[start:]
        with patch("analytics.supervised_data", return_value=(features, labels)):
            original = analyze(data)
        with patch("analytics.supervised_data", return_value=(features, changed)):
            altered = analyze(data)
        self.assertEqual(original.model_name, altered.model_name)
        pd.testing.assert_series_equal(original.selection_scores, altered.selection_scores)

    def test_added_features_are_finite_for_flat_candles(self):
        source = constant_path(0)
        source["High"] = source["Low"] = source["Close"]
        data = add_indicators(source)
        self.assertEqual(data.Close_position.iloc[-1], .5)
        self.assertTrue(np.isfinite(data[FEATURES].iloc[-1]).all())


if __name__ == "__main__":
    unittest.main()
