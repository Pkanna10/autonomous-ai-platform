"""Clear cases only: any threshold near the alarm level passes."""

import unittest

from classify.model import predict, readings


class PredictTest(unittest.TestCase):
    def test_a_low_reading_is_no_alarm(self) -> None:
        self.assertEqual(predict(10), "0")

    def test_a_high_reading_is_an_alarm(self) -> None:
        self.assertEqual(predict(9990), "1")

    def test_readings_are_deterministic(self) -> None:
        self.assertEqual(readings(5), readings(5))
