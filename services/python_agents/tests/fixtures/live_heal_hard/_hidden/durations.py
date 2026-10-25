"""Hidden check for durations (a control): a bare number stays refused."""

import unittest

from durations.config import load_settings
from durations.parse import parse_duration


class HiddenCheck(unittest.TestCase):
    def test_a_bare_number_is_refused(self):
        for text in ("90", " 90 ", "0"):
            with self.assertRaises(ValueError):
                parse_duration(text)

    def test_settings_with_a_bare_number_are_refused(self):
        with self.assertRaises(ValueError):
            load_settings({"timeout": "90"})

    def test_units_still_parse(self):
        self.assertEqual(parse_duration("1h1m1s"), 3661)
        self.assertEqual(load_settings({"retry_after": "90s"}), {"retry_after": 90})


if __name__ == "__main__":
    unittest.main()
