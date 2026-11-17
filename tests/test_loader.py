import csv
import unittest
from pathlib import Path

from data_loader import columns_for_row, numeric_value


class LoaderFormatTests(unittest.TestCase):
    def test_repairs_expanded_historical_rows(self):
        short_header = ["Station", "SynopticID", "TIMESTAMP", "RH", "SlrW_Avg", "FuelM_Avg", "PA_uS_Avg"]
        expanded_row = ["BlackberryHill", "SJS06", "2025-04-10 02:35:00",
                        "NAN", "54.46", "0.0", "10.58", "7.661", "18.09",
                        "0.163", "134.8", "7.994", "0.412"]
        columns = columns_for_row(short_header, expanded_row)
        self.assertEqual(columns[3], "AirTF_Avg")
        self.assertEqual(columns[-1], "WindSpeed_mph_max")

    def test_missing_and_sentinel_values_are_skipped(self):
        for value in ("", "NAN", "null", "-1000"):
            self.assertIsNone(numeric_value(value))
        self.assertEqual(numeric_value("0"), 0)
        self.assertAlmostEqual(numeric_value("54.46"), 54.46)

    def test_repairs_shortened_pge_rows(self):
        header = ["Station", "SynopticID", "TIMESTAMP", "AirTF_Avg", "RH",
                  "Rain_in_Tot", "SlrW_Avg", "FuelT_C_Avg", "FuelM_Avg",
                  "PA_uS_Avg", "WindSpeed_mph_avg", "WindDir_avg",
                  "WindDir_StdDev", "WindSpeed_mph_max"]
        shortened = ["PGESanRamon", "SJS61", "2026-05-13 23:15:00", "67.4",
                     "53.91", "0", "700.7", "-1000", "10.72", "200.2",
                     "20.95", "15.04"]
        columns = columns_for_row(header, shortened)
        self.assertNotIn("FuelM_Avg", columns)
        self.assertNotIn("PA_uS_Avg", columns)
        self.assertEqual(columns[8], "WindSpeed_mph_avg")

    def test_downloaded_station_rows_use_supported_layouts(self):
        root = Path(__file__).resolve().parents[1] / "data" / "raw"
        files = list(root.glob("*/*.csv"))
        if not files:
            self.skipTest("downloaded data archive is not present")
        for path in files:
            with self.subTest(file=path.name), path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.reader(source)
                header = next(reader)
                for line_number, row in enumerate(reader, 2):
                    try:
                        columns_for_row(header, row)
                    except ValueError as error:
                        self.fail(f"{path.name}:{line_number}: {error}")


if __name__ == "__main__":
    unittest.main()
