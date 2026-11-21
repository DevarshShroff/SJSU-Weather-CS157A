import unittest
from datetime import datetime

from app import app, condition_met, parse_timestamp, reading_window
from data_loader import VARIABLES
from station_catalog import STATION_VARIABLES


class ApplicationSmokeTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = app.test_client()

    def test_public_pages_render(self):
        for path in ("/", "/login", "/register"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    def test_protected_page_redirects_to_login(self):
        response = self.client.get("/observations")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_post_without_csrf_is_rejected(self):
        response = self.client.post("/logout")
        self.assertEqual(response.status_code, 400)

    def test_all_templates_compile(self):
        for name in app.jinja_env.list_templates():
            app.jinja_env.get_template(name)


class ImportHelperTests(unittest.TestCase):
    def test_supported_timestamps(self):
        self.assertEqual(parse_timestamp("2026-10-18T12:30"), datetime(2026, 10, 18, 12, 30))
        self.assertEqual(parse_timestamp("10/18/2026 12:30"), datetime(2026, 10, 18, 12, 30))
        self.assertEqual(parse_timestamp("202610181230"), datetime(2026, 10, 18, 12, 30))

    def test_alert_operators(self):
        self.assertTrue(condition_met(31, ">", 30))
        self.assertTrue(condition_met(30, ">=", 30))
        self.assertTrue(condition_met(29, "<", 30))
        self.assertTrue(condition_met(30, "<=", 30))
        self.assertTrue(condition_met(30, "=", 30))


class SeriesFilterTests(unittest.TestCase):
    span = (datetime(2025, 4, 1), datetime(2026, 5, 18, 4, 25))

    def test_default_window_is_last_72_hours_of_the_series(self):
        self.assertEqual(reading_window({}, self.span),
                         (datetime(2026, 5, 15, 4, 25), datetime(2026, 5, 18, 4, 25)))

    def test_only_end_given_still_bounds_the_start(self):
        start, end = reading_window({"end": "2025-06-10T00:00"}, self.span)
        self.assertEqual((start, end), (datetime(2025, 6, 7), datetime(2025, 6, 10)))

    def test_invalid_dates_fall_back_to_default_and_reversed_dates_swap(self):
        self.assertEqual(reading_window({"start": "bad"}, self.span), reading_window({}, self.span))
        start, end = reading_window({"start": "2025-06-10T00:00", "end": "2025-06-01T00:00"}, self.span)
        self.assertLess(start, end)

    def test_station_dictionary_uses_known_variable_codes(self):
        known = {code for code, _name, _unit in VARIABLES.values()}
        for station, codes in STATION_VARIABLES.items():
            self.assertTrue(set(codes) <= known, station)


if __name__ == "__main__":
    unittest.main()
