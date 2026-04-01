import json
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from cli_anything.eagle.eagle_cli import cli


class EagleCliTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.app_info")
    def test_app_info_json(self, mock_app_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_app_info.return_value = {"status": "success", "data": {"version": "4.0.0"}}
        result = self.runner.invoke(cli, ["--json", "app", "info"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["version"], "4.0.0")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.folder_list")
    def test_folder_tree_plain_text(self, mock_folder_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_folder_list.return_value = {
            "status": "success",
            "data": [
                {
                    "id": "root",
                    "name": "Root",
                    "children": [{"id": "child", "name": "Child", "children": []}],
                }
            ],
        }
        result = self.runner.invoke(cli, ["folder", "tree"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("- Root [root]", result.output)
        self.assertIn("  - Child [child]", result.output)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.raw_request")
    def test_raw_request_parses_query_and_body(self, mock_raw_request, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_raw_request.return_value = {"status": "success", "data": {"ok": True}}
        result = self.runner.invoke(
            cli,
            [
                "--json",
                "raw",
                "request",
                "POST",
                "/api/item/update",
                "--query",
                "dryRun=true",
                "--body-json",
                '{"id":"abc"}',
            ],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        mock_raw_request.assert_called_once_with(
            "POST",
            "/api/item/update",
            params={"dryRun": "true"},
            payload={"id": "abc"},
        )


if __name__ == "__main__":
    unittest.main()
