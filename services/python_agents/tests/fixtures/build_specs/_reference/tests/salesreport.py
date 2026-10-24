import unittest

from salesreport import build_report

HEADER = "date,region,product,units,unit_price"


class BuildReportTest(unittest.TestCase):
    def test_the_worked_example(self):
        text = (
            HEADER + "\n2025-01-05,EAST,gear-02,4,10.00\n"
            "2025-01-20,EAST,bolt-01,3,8.08\n2025-02-01,WEST,gear-02,1,0.99\n"
        )
        self.assertEqual(
            build_report(text),
            "region,month,orders,units,revenue,top_product\n"
            "EAST,2025-01,2,7,64.24,gear-02\nWEST,2025-02,1,1,0.99,gear-02\n"
            "TOTAL,,3,8,65.23,\n",
        )

    def test_no_records(self):
        self.assertEqual(
            build_report(HEADER),
            "region,month,orders,units,revenue,top_product\nTOTAL,,0,0,0.00,\n",
        )

    def test_a_wrong_header_raises(self):
        with self.assertRaises(ValueError):
            build_report("date,region\n")

    def test_a_tie_goes_to_the_first_name(self):
        text = HEADER + "\n2024-05-01,N,b,2,1.00\n2024-05-02,N,a,2,1.00\n"
        self.assertIn("N,2024-05,2,4,4.00,a\n", build_report(text))

    def test_empty_lines_are_ignored_and_cents_are_exact(self):
        text = HEADER + "\n\n2024-01-01,S,x,3,0.10\n\n"
        self.assertTrue(build_report(text).endswith("S,2024-01,1,3,0.30,x\nTOTAL,,1,3,0.30,\n"))

    def test_groups_sort_by_region_then_month(self):
        text = HEADER + "\n2024-02-01,B,x,1,1.00\n2024-01-01,B,x,1,1.00\n2024-03-01,A,x,1,1.00\n"
        lines = build_report(text).splitlines()[1:-1]
        self.assertEqual([l.split(",")[:2] for l in lines], [["A", "2024-03"], ["B", "2024-01"], ["B", "2024-02"]])
