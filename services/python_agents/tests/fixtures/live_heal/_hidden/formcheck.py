"""Hidden check for formcheck: no problem carries over between records."""

import unittest

from formcheck.batch import validate_all
from formcheck.rules import ValidationError, check_record, validate

BAD = {"name": "", "email": "kim@example.org", "age": "31"}
WORSE = {"name": "Al", "email": "@nowhere", "age": "old"}
LEE = {"name": "Lee", "email": "lee@example.org", "age": "27"}
MO = {"name": "Mo", "email": "mo@example.org", "age": "45"}


class HiddenCheck(unittest.TestCase):
    def test_a_good_record_after_a_bad_one_is_accepted(self):
        with self.assertRaises(ValidationError):
            validate(BAD)
        self.assertEqual(validate(LEE), LEE)

    def test_each_check_starts_empty(self):
        self.assertEqual(
            check_record(WORSE), ["email is invalid", "age must be a whole number"]
        )
        self.assertEqual(check_record(LEE), [])

    def test_a_batch_reports_only_the_bad_records(self):
        valid, errors = validate_all([BAD, LEE, WORSE, MO])
        self.assertEqual(valid, [LEE, MO])
        self.assertEqual(
            errors,
            {0: "name is required", 2: "email is invalid; age must be a whole number"},
        )


if __name__ == "__main__":
    unittest.main()
