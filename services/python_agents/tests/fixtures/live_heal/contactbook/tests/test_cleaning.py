import unittest

from contactbook.cleaning import merge_contacts, normalise_email
from contactbook.export import export_csv


class CleaningTest(unittest.TestCase):
    def test_email_is_trimmed_and_lower_cased(self):
        self.assertEqual(
            normalise_email({"email": " Ann@Example.COM "}), "ann@example.com"
        )

    def test_records_with_one_email_are_merged(self):
        merged = merge_contacts(
            [
                {"name": "Ann", "email": "ann@example.com", "phone": ""},
                {"name": "Ann B.", "email": "ANN@example.com", "phone": "555-0100"},
            ]
        )
        self.assertEqual(
            merged, [{"name": "Ann", "email": "ann@example.com", "phone": "555-0100"}]
        )


class ExportTest(unittest.TestCase):
    def test_export(self):
        text = export_csv(
            [
                {"name": "Ann", "email": "ann@example.com"},
                {"name": "Bo", "email": "bo@example.com"},
            ]
        )
        self.assertEqual(text, "name,email\nAnn,ann@example.com\nBo,bo@example.com\n")


if __name__ == "__main__":
    unittest.main()
