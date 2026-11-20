import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import app, condition_met, parse_timestamp


class BackendIntegrationTests(unittest.TestCase):
    def test_root_entrypoint_finds_schema_and_loader_commands(self):
        self.assertTrue((Path(app.root_path) / "schema.sql").is_file())
        for command in ("init-db", "load-data", "data-stats", "optimize-db"):
            self.assertIn(command, app.cli.commands)

    def test_init_db_uses_root_schema(self):
        connection = MagicMock()
        with patch("app.pymysql.connect", return_value=connection):
            result = app.test_cli_runner().invoke(args=["init-db"])
        self.assertIsNone(result.exception)
        statements = [call.args[0] for call in connection.cursor.return_value.__enter__.return_value.execute.call_args_list]
        self.assertTrue(any("CREATE DATABASE" in sql for sql in statements))
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS observations" in sql for sql in statements))
        connection.commit.assert_called_once()
        connection.close.assert_called_once()

    def test_load_data_uses_root_archive(self):
        connection = MagicMock()
        with patch("app.pymysql.connect", return_value=connection), patch(
            "data_loader.load_archive", return_value={"files": 0, "skipped": 0, "rows": 0}
        ) as load_archive:
            result = app.test_cli_runner().invoke(args=["load-data"])
        self.assertIsNone(result.exception)
        self.assertEqual(Path(load_archive.call_args.args[1]), Path(app.root_path) / "data" / "raw")
        connection.close.assert_called_once()

    def test_protected_route_and_csrf(self):
        with app.test_client() as client:
            response = client.get("/observations")
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login", response.headers["Location"])
            self.assertEqual(client.post("/logout").status_code, 400)

    def test_alert_comparison_and_timestamp_parsing(self):
        self.assertTrue(condition_met(10, ">=", 10))
        self.assertFalse(condition_met(10, "<", 10))
        self.assertEqual(str(parse_timestamp("2025-04-10 02:35:00")), "2025-04-10 02:35:00")


if __name__ == "__main__":
    unittest.main()
