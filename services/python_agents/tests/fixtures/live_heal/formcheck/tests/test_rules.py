import unittest

from formcheck.batch import validate_all
from formcheck.rules import validate

KIM = {"name": "Kim", "email": "kim@example.org", "age": "31"}
LEE = {"name": "Lee", "email": "lee@example.org", "age": "27"}


class RulesTest(unittest.TestCase):
    def test_a_good_record_is_returned_unchanged(self):
        self.assertEqual(validate(KIM), KIM)

    def test_a_batch_of_good_records(self):
        self.assertEqual(validate_all([KIM, LEE]), ([KIM, LEE], {}))


if __name__ == "__main__":
    unittest.main()
