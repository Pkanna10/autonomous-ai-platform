"""Hidden check for contactbook: contacts without an email are kept apart."""

import unittest

from contactbook.cleaning import merge_contacts
from contactbook.export import export_csv


class HiddenCheck(unittest.TestCase):
    def test_contacts_without_an_email_are_kept(self):
        merged = merge_contacts(
            [
                {"name": "Ann", "email": "ann@example.com"},
                {"name": "Bo"},
                {"name": "Cy", "email": None},
                {"name": "Ann B.", "email": "ANN@example.com ", "phone": "555-0100"},
            ]
        )
        self.assertEqual(sorted(c["name"] for c in merged), ["Ann", "Bo", "Cy"])
        ann = next(c for c in merged if c["name"] == "Ann")
        self.assertEqual((ann["email"], ann["phone"]), ("ann@example.com", "555-0100"))

    def test_two_contacts_without_an_email_are_not_merged(self):
        merged = merge_contacts([{"name": "Bo"}, {"name": "Dee", "email": None}])
        self.assertEqual(sorted(c["name"] for c in merged), ["Bo", "Dee"])

    def test_export_lists_contacts_without_an_email(self):
        lines = export_csv([{"name": "Bo"}, {"name": "Ann", "email": "a@x.org"}])
        self.assertEqual(lines.splitlines()[0], "name,email")
        self.assertCountEqual(lines.splitlines()[1:], ["Bo,", "Ann,a@x.org"])


if __name__ == "__main__":
    unittest.main()
