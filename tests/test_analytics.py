import unittest

import numpy as np
import pandas as pd

from analytics import (add_indicators, analyze, chronological_split,
                       demo_history, normalize_history, supervised_data)


def constant_path(step):
    close = 200 + np.arange(150) * step
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                         "Close": close, "Volume": 100},
                        index=pd.bdate_range("2025-01-01", periods=150))


class IndicatorTests(unittest.TestCase):
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
        _, test_x, train_y, test_y = chronological_split(features, labels)
        result = analyze(data)
        self.assertEqual(result.validation_sessions, len(test_x))
        self.assertAlmostEqual(result.baseline, (test_y == int(train_y.mean() >= .5)).mean())
        self.assertTrue(0 <= result.upward_score <= 1)
        self.assertTrue(0 <= result.accuracy <= 1)


if __name__ == "__main__":
    unittest.main()
