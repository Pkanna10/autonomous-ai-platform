import unittest

from durations.config import load_settings
from durations.parse import parse_duration


class ParseTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(parse_duration("90s"), 90)
        self.assertEqual(parse_duration("2m"), 120)
        self.assertEqual(parse_duration(" 1h30m "), 5400)

    def test_garbage_is_refused(self):
        with self.assertRaises(ValueError):
            parse_duration("soon")

    def test_settings(self):
        settings = load_settings({"timeout": "2m", "name": "w1"})
        self.assertEqual(settings, {"timeout": 120, "name": "w1"})


if __name__ == "__main__":
    unittest.main()
