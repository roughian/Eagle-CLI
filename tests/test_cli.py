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

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.folder_list")
    def test_folder_find_exact_returns_flat_match(self, mock_folder_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_folder_list.return_value = {
            "status": "success",
            "data": [
                {"id": "root", "name": "Root", "children": [{"id": "child", "name": "Child", "children": []}]}
            ],
        }
        result = self.runner.invoke(cli, ["--json", "folder", "find", "Child", "--exact"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"][0]["path"], "Root/Child")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.folder_list")
    def test_item_list_resolves_folder_path(self, mock_folder_list, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_folder_list.return_value = {
            "status": "success",
            "data": [
                {"id": "root", "name": "Root", "children": [{"id": "child", "name": "Child", "children": []}]}
            ],
        }
        mock_item_list.return_value = {"status": "success", "data": []}
        result = self.runner.invoke(cli, ["--json", "item", "list", "--folder-path", "Root/Child"])
        self.assertEqual(result.exit_code, 0, result.output)
        mock_item_list.assert_called_once_with(
            limit=20,
            offset=0,
            orderBy=None,
            keyword=None,
            ext=None,
            tags=None,
            folders="child",
        )

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.folder_list")
    def test_folder_ensure_path_dry_run_plans_creation(self, mock_folder_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_folder_list.return_value = {
            "status": "success",
            "data": [{"id": "root", "name": "Root", "children": []}],
        }
        result = self.runner.invoke(cli, ["--json", "--dry-run", "folder", "ensure-path", "Root/NewLeaf"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "dry-run")
        self.assertEqual(payload["data"]["leaf_path"], "Root/NewLeaf")
        self.assertEqual(payload["data"]["planned"][0]["payload"]["folderName"], "NewLeaf")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_item_bulk_update_dry_run_uses_resolved_payloads(self, mock_item_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.return_value = {
            "status": "success",
            "data": {"id": "abc", "name": "Sample", "tags": ["old"]},
        }
        result = self.runner.invoke(
            cli,
            ["--json", "--dry-run", "item", "bulk-update", "--item-id", "abc", "--add-tag", "new"],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "dry-run")
        self.assertEqual(payload["data"]["matched_count"], 1)
        self.assertEqual(payload["data"]["operations"][0]["payload"]["tags"], ["old", "new"])

    @patch("cli_anything.eagle.eagle_cli.set_preset")
    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_preset_save_item_list_stores_params(self, mock_load, _mock_save, mock_set_preset):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        result = self.runner.invoke(
            cli,
            ["--json", "preset", "save-item-list", "designs", "--keyword", "design", "--tag", "ui", "--folder-path", "Root/Child"],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        mock_set_preset.assert_called_once()
        args = mock_set_preset.call_args.args
        self.assertEqual(args[0], "designs")
        self.assertEqual(args[1]["kind"], "item-list")
        self.assertEqual(args[1]["params"]["keyword"], "design")

    @patch("cli_anything.eagle.eagle_cli.get_preset")
    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.folder_list")
    def test_preset_run_item_list_executes_saved_query(
        self,
        mock_folder_list,
        mock_item_list,
        mock_load,
        _mock_save,
        mock_get_preset,
    ):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_folder_list.return_value = {
            "status": "success",
            "data": [{"id": "root", "name": "Root", "children": [{"id": "child", "name": "Child", "children": []}]}],
        }
        mock_item_list.return_value = {"status": "success", "data": []}
        mock_get_preset.return_value = {
            "kind": "item-list",
            "params": {
                "limit": 10,
                "offset": 0,
                "order_by": None,
                "keyword": "design",
                "ext": None,
                "tags": ["ui"],
                "folders": [],
                "folder_names": [],
                "folder_paths": ["Root/Child"],
            },
        }
        result = self.runner.invoke(cli, ["--json", "preset", "run-item-list", "designs"])
        self.assertEqual(result.exit_code, 0, result.output)
        mock_item_list.assert_called_once_with(
            limit=10,
            offset=0,
            orderBy=None,
            keyword="design",
            ext=None,
            tags="ui",
            folders="child",
        )

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_plan_save_last_writes_operations_to_disk(self, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        state = SessionState()
        state.last_command = "item bulk-update"
        state.last_response = {
            "status": "dry-run",
            "data": {
                "operations": [{"method": "POST", "endpoint": "/api/item/update", "payload": {"id": "abc"}}]
            },
        }
        mock_load.return_value = state
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, ["--json", "plan", "save-last", "plan.json"])
            self.assertEqual(result.exit_code, 0, result.output)
            with open("plan.json", "r", encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["kind"], "eagle-cli-plan")
            self.assertEqual(saved["operations"][0]["endpoint"], "/api/item/update")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.raw_request")
    def test_plan_apply_executes_operations(self, mock_raw_request, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_raw_request.return_value = {"status": "success"}
        with self.runner.isolated_filesystem():
            with open("plan.json", "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "kind": "eagle-cli-plan",
                        "version": 1,
                        "operations": [{"method": "POST", "endpoint": "/api/item/update", "payload": {"id": "abc"}}],
                    },
                    handle,
                )
            result = self.runner.invoke(cli, ["--json", "plan", "apply", "plan.json"])
            self.assertEqual(result.exit_code, 0, result.output)
            mock_raw_request.assert_called_once_with("POST", "/api/item/update", payload={"id": "abc"})


if __name__ == "__main__":
    unittest.main()
