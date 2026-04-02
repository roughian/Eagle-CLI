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
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_item_list_all_pages_until_short_page(self, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_list.side_effect = [
            {"status": "success", "data": [{"id": "a"}, {"id": "b"}]},
            {"status": "success", "data": [{"id": "c"}]},
        ]
        result = self.runner.invoke(cli, ["--json", "item", "list", "--all", "--limit", "2"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(len(payload["data"]), 3)
        self.assertEqual(mock_item_list.call_count, 2)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_snapshot_create_writes_document(self, mock_item_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.return_value = {
            "status": "success",
            "data": {"id": "abc", "name": "Sample", "tags": ["ui"], "annotation": "", "url": "", "folders": ["f1"]},
        }
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, ["--json", "snapshot", "create", "snap.json", "--item-id", "abc"])
            self.assertEqual(result.exit_code, 0, result.output)
            with open("snap.json", "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["kind"], "eagle-cli-snapshot")
            self.assertEqual(payload["items"][0]["id"], "abc")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_snapshot_diff_reports_metadata_changes(self, mock_item_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.return_value = {
            "status": "success",
            "data": {"id": "abc", "name": "Current", "tags": [], "annotation": "changed", "url": "", "folders": ["f1"]},
        }
        with self.runner.isolated_filesystem():
            with open("snap.json", "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "kind": "eagle-cli-snapshot",
                        "version": 1,
                        "items": [{"id": "abc", "name": "Saved", "tags": ["ui"], "annotation": "", "url": "", "folders": ["f2"]}],
                    },
                    handle,
                )
            result = self.runner.invoke(
                cli,
                ["--json", "snapshot", "diff", "snap.json", "--include-names", "--include-folders"],
            )
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["counts"]["changed_items"], 1)
        fields = [row["field"] for row in payload["data"]["changed"][0]["differences"]]
        self.assertIn("tags", fields)
        self.assertIn("annotation", fields)
        self.assertIn("name", fields)
        self.assertIn("folders", fields)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_snapshot_restore_dry_run_includes_bridge_ops(self, mock_item_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.return_value = {
            "status": "success",
            "data": {"id": "abc", "name": "Current", "tags": [], "annotation": "", "url": "", "folders": ["old-folder"]},
        }
        with self.runner.isolated_filesystem():
            with open("snap.json", "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "kind": "eagle-cli-snapshot",
                        "version": 1,
                        "items": [
                            {
                                "id": "abc",
                                "name": "Saved",
                                "tags": ["ui"],
                                "annotation": "",
                                "url": "",
                                "folders": ["new-folder"],
                            }
                        ],
                    },
                    handle,
                )
            result = self.runner.invoke(
                cli,
                ["--json", "--dry-run", "snapshot", "restore", "snap.json", "--restore-names", "--restore-folders"],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(len(payload["data"]["rename_operations"]), 1)
            self.assertEqual(len(payload["data"]["move_operations"]), 1)

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

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_item_bulk_update_loads_item_ids_from_file(self, mock_item_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.side_effect = [
            {"status": "success", "data": {"id": "abc", "name": "A", "tags": []}},
            {"status": "success", "data": {"id": "def", "name": "B", "tags": []}},
        ]
        with self.runner.isolated_filesystem():
            with open("items.json", "w", encoding="utf-8") as handle:
                json.dump([{"id": "abc", "name": "A"}, {"id": "def", "name": "B"}], handle)
            result = self.runner.invoke(
                cli,
                ["--json", "--dry-run", "item", "bulk-update", "--item-file", "items.json", "--add-tag", "reviewed"],
            )
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["matched_count"], 2)
        self.assertEqual(mock_item_info.call_count, 2)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_item_bulk_update_skip_unchanged_can_save_matches(self, mock_item_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.return_value = {
            "status": "success",
            "data": {"id": "abc", "name": "Sample", "tags": ["old"], "annotation": "", "url": ""},
        }
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(
                cli,
                [
                    "--json",
                    "--dry-run",
                    "item",
                    "bulk-update",
                    "--item-id",
                    "abc",
                    "--add-tag",
                    "old",
                    "--skip-unchanged",
                    "--save-matches",
                    "matches.json",
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            with open("matches.json", "r", encoding="utf-8") as handle:
                matches = json.load(handle)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["matched_count"], 1)
        self.assertEqual(payload["data"]["operation_count"], 0)
        self.assertEqual(len(payload["data"]["skipped_unchanged"]), 1)
        self.assertEqual(matches[0]["id"], "abc")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_item_rename_bulk_dry_run_builds_bridge_operations(self, mock_item_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.return_value = {"status": "success", "data": {"id": "abc", "name": "Sample"}}
        result = self.runner.invoke(
            cli,
            ["--json", "--dry-run", "item", "rename-bulk", "--item-id", "abc", "--prefix", "new-"],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["operations"][0]["new_name"], "new-Sample")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.folder_list")
    def test_item_move_bulk_dry_run_resolves_target_folder(self, mock_folder_list, mock_item_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.return_value = {"status": "success", "data": {"id": "abc", "name": "Sample", "folders": []}}
        mock_folder_list.return_value = {
            "status": "success",
            "data": [{"id": "root", "name": "Root", "children": [{"id": "child", "name": "Child", "children": []}]}],
        }
        result = self.runner.invoke(
            cli,
            ["--json", "--dry-run", "item", "move-bulk", "--item-id", "abc", "--target-folder-path", "Root/Child"],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["operations"][0]["folder_ids"], ["child"])

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_audit_duplicates_groups_items(self, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_list.return_value = {
            "status": "success",
            "data": [
                {"id": "a", "name": "Same", "url": "", "ext": "png", "size": 10},
                {"id": "b", "name": "Same", "url": "", "ext": "png", "size": 10},
            ],
        }
        result = self.runner.invoke(cli, ["--json", "audit", "duplicates", "--keyword", "same"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["modes"][0]["group_count"], 1)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_audit_cleanup_counts_missing_fields(self, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_list.return_value = {
            "status": "success",
            "data": [
                {"id": "a", "name": "Alpha", "tags": [], "annotation": "", "url": "", "folders": []},
                {"id": "b", "name": "Beta", "tags": ["ref"], "annotation": "ok", "url": "https://example.com", "folders": ["f1"]},
            ],
        }
        result = self.runner.invoke(cli, ["--json", "audit", "cleanup", "--keyword", "alpha"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["counts"]["untagged"], 1)
        self.assertEqual(payload["data"]["counts"]["unfiled"], 1)
        self.assertEqual(payload["data"]["counts"]["missing_url"], 1)
        self.assertEqual(payload["data"]["counts"]["missing_annotation"], 1)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_audit_dedupe_plan_writes_move_to_trash_plan(self, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_list.return_value = {
            "status": "success",
            "data": [
                {"id": "a", "name": "Same", "size": 10},
                {"id": "b", "name": "Same", "size": 20},
                {"id": "c", "name": "Other", "size": 5},
            ],
        }
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(
                cli,
                ["--json", "audit", "dedupe-plan", "dedupe.json", "--keyword", "same", "--mode", "name", "--keep", "largest"],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            with open("dedupe.json", "r", encoding="utf-8") as handle:
                saved = json.load(handle)
        self.assertEqual(saved["kind"], "eagle-cli-plan")
        self.assertEqual(saved["operations"][0]["endpoint"], "/api/item/moveToTrash")
        self.assertEqual(saved["operations"][0]["payload"]["itemIds"], ["a"])

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.folder_list")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_organize_apply_dry_run_combines_metadata_move_and_rename(
        self, mock_item_info, mock_folder_list, mock_load, _mock_save
    ):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.return_value = {
            "status": "success",
            "data": {"id": "abc", "name": "Sample", "tags": [], "annotation": "", "url": "", "folders": ["root"]},
        }
        mock_folder_list.return_value = {
            "status": "success",
            "data": [{"id": "root", "name": "Root", "children": [{"id": "child", "name": "Child", "children": []}]}],
        }
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(
                cli,
                [
                    "--json",
                    "--dry-run",
                    "organize",
                    "apply",
                    "--item-id",
                    "abc",
                    "--add-tag",
                    "reviewed",
                    "--name-prefix",
                    "ui-",
                    "--target-folder-path",
                    "Root/Child",
                    "--save-snapshot",
                    "organize-snapshot.json",
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            with open("organize-snapshot.json", "r", encoding="utf-8") as handle:
                self.assertTrue(handle.read())
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["metadata"]["status"], "dry-run")
        self.assertEqual(payload["data"]["metadata"]["data"]["operation_count"], 1)
        self.assertEqual(len(payload["data"]["move_operations"]), 1)
        self.assertEqual(len(payload["data"]["rename_operations"]), 1)
        self.assertEqual(payload["data"]["saved_snapshot"], "organize-snapshot.json")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_bridge_export_plugin_writes_manifest(self, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, ["--json", "bridge", "export-plugin", "plugin-copy"])
            self.assertEqual(result.exit_code, 0, result.output)
            with open("plugin-copy/manifest.json", "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["name"], "CLI-Anything Eagle Bridge")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_item_bulk_update_rejects_over_max_items(self, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_list.return_value = {
            "status": "success",
            "data": [{"id": "a", "name": "One"}, {"id": "b", "name": "Two"}],
        }
        result = self.runner.invoke(
            cli,
            ["item", "bulk-update", "--keyword", "ui", "--add-tag", "reviewed", "--max-items", "1"],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("exceeds --max-items 1", result.output)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.folder_list")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_item_stats_summarizes_counts(self, mock_item_list, mock_folder_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_folder_list.return_value = {
            "status": "success",
            "data": [{"id": "root", "name": "Root", "children": [{"id": "child", "name": "Child", "children": []}]}],
        }
        mock_item_list.return_value = {
            "status": "success",
            "data": [
                {"id": "a", "ext": "png", "tags": ["ui"], "folders": ["child"], "annotation": "note", "url": "https://x"},
                {"id": "b", "ext": "png", "tags": [], "folders": ["child"], "annotation": "", "url": ""},
            ],
        }
        result = self.runner.invoke(cli, ["--json", "item", "stats"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["total_items"], 2)
        self.assertEqual(payload["data"]["tagged_items"], 1)
        self.assertEqual(payload["data"]["extensions"][0]["ext"], "png")
        self.assertEqual(payload["data"]["folders"][0]["folder_path"], "Root/Child")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.library_info")
    def test_library_summary_reports_rule_stats(self, mock_library_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_library_info.return_value = {
            "status": "success",
            "data": {
                "applicationVersion": "4.0.0",
                "library": {"name": "Demo", "path": "/tmp/demo.library"},
                "folders": [{"id": "root", "name": "Root", "children": []}],
                "smartFolders": [
                    {
                        "id": "sf1",
                        "name": "PNG Only",
                        "children": [],
                        "conditions": [
                            {
                                "boolean": "TRUE",
                                "match": "AND",
                                "rules": [{"property": "type", "method": "equal", "value": "png"}],
                            }
                        ],
                    }
                ],
                "quickAccess": [],
                "tagsGroups": [],
            },
        }
        result = self.runner.invoke(cli, ["--json", "library", "summary"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["library_name"], "Demo")
        self.assertEqual(payload["data"]["smart_rule_count"], 1)
        self.assertEqual(payload["data"]["smart_rule_properties"], ["type"])

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

    @patch("cli_anything.eagle.eagle_cli.get_preset")
    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_preset_run_bulk_update_builds_dry_run_operations(self, mock_item_list, mock_load, _mock_save, mock_get_preset):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_get_preset.return_value = {
            "kind": "bulk-update",
            "selector": {
                "item_ids": [],
                "limit": 50,
                "offset": 0,
                "order_by": None,
                "keyword": "ui",
                "ext": None,
                "tags": [],
                "folders": [],
                "folder_names": [],
                "folder_paths": [],
            },
            "mutation": {"set_tags": [], "add_tags": ["reviewed"], "annotation": None, "source_url": None, "star": None},
        }
        mock_item_list.return_value = {"status": "success", "data": [{"id": "abc", "name": "Sample", "tags": ["old"]}]}
        result = self.runner.invoke(cli, ["--json", "--dry-run", "preset", "run-bulk-update", "review-ui"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "dry-run")
        self.assertEqual(payload["data"]["matched_count"], 1)
        self.assertEqual(payload["data"]["operations"][0]["payload"]["tags"], ["old", "reviewed"])

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_item_add_dir_dry_run_writes_manifest(self, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        with self.runner.isolated_filesystem():
            import os

            os.makedirs("assets/nested", exist_ok=True)
            with open("assets/a.png", "w", encoding="utf-8") as handle:
                handle.write("demo")
            with open("assets/nested/b.jpg", "w", encoding="utf-8") as handle:
                handle.write("demo")
            result = self.runner.invoke(
                cli,
                ["--json", "--dry-run", "item", "add-dir", "assets", "--recursive", "--ext", "png", "--save-manifest", "manifest.json"],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload["status"], "dry-run")
            self.assertEqual(len(payload["data"]["payload"]["items"]), 1)
            with open("manifest.json", "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["kind"], "eagle-cli-add-paths-manifest")
            self.assertEqual(len(manifest["items"]), 1)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.library_info")
    def test_smart_folder_rules_normalize_conditions(self, mock_library_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_library_info.return_value = {
            "status": "success",
            "data": {
                "smartFolders": [
                    {
                        "id": "sf1",
                        "name": "Images",
                        "children": [],
                        "conditions": [
                            {
                                "boolean": "TRUE",
                                "match": "AND",
                                "rules": [{"property": "type", "method": "equal", "value": "png"}],
                            }
                        ],
                    }
                ]
            },
        }
        result = self.runner.invoke(cli, ["--json", "smart-folder", "rules", "--name", "Images"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"][0]["property"], "type")
        self.assertEqual(payload["data"][0]["method"], "equal")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.library_info")
    def test_smart_folder_run_translates_into_item_query(self, mock_library_info, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_library_info.return_value = {
            "status": "success",
            "data": {
                "smartFolders": [
                    {
                        "id": "sf1",
                        "name": "Images",
                        "children": [],
                        "conditions": [
                            {
                                "boolean": "TRUE",
                                "match": "AND",
                                "rules": [
                                    {"property": "type", "method": "equal", "value": "png"},
                                    {"property": "folders", "method": "intersection", "value": ["folder-1"]},
                                ],
                            }
                        ],
                    }
                ]
            },
        }
        mock_item_list.return_value = {"status": "success", "data": [{"id": "item-1", "name": "A"}]}
        result = self.runner.invoke(cli, ["--json", "smart-folder", "run", "--name", "Images"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["item_count"], 1)
        mock_item_list.assert_called_once_with(
            limit=20,
            offset=0,
            orderBy=None,
            keyword=None,
            ext="png",
            tags=None,
            folders="folder-1",
        )

    @patch("cli_anything.eagle.eagle_cli.save_presets")
    @patch("cli_anything.eagle.eagle_cli.load_presets")
    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_preset_import_applies_prefix(self, mock_load, _mock_save, mock_load_presets, mock_save_presets):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_load_presets.return_value = {"version": 1, "presets": {}}
        with self.runner.isolated_filesystem():
            with open("bundle.json", "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "kind": "eagle-cli-preset-bundle",
                        "version": 1,
                        "presets": {"designs": {"kind": "item-list", "params": {"keyword": "ui"}}},
                    },
                    handle,
                )
            result = self.runner.invoke(cli, ["--json", "preset", "import", "bundle.json", "--prefix", "team-"])
            self.assertEqual(result.exit_code, 0, result.output)
        saved = mock_save_presets.call_args.args[0]
        self.assertIn("team-designs", saved["presets"])

    @patch("cli_anything.eagle.eagle_cli.load_presets")
    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_preset_export_writes_selected_bundle(self, mock_load, _mock_save, mock_load_presets):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_load_presets.return_value = {
            "version": 1,
            "presets": {
                "designs": {"kind": "item-list", "params": {"keyword": "ui"}},
                "review": {"kind": "bulk-update", "selector": {}, "mutation": {"add_tags": ["reviewed"]}},
            },
        }
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, ["--json", "preset", "export", "bundle.json", "designs"])
            self.assertEqual(result.exit_code, 0, result.output)
            with open("bundle.json", "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(sorted(payload["presets"].keys()), ["designs"])

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_item_export_writes_csv(self, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_list.return_value = {"status": "success", "data": [{"id": "abc", "name": "Sample", "tags": ["ui"]}]}
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, ["--json", "item", "export", "items.csv", "--format", "csv"])
            self.assertEqual(result.exit_code, 0, result.output)
            with open("items.csv", "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("id,name,tags", content)
            self.assertIn("abc,Sample", content)

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

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli._bridge_request")
    def test_plan_apply_executes_bridge_operations(self, mock_bridge_request, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_bridge_request.return_value = {"status": "success"}
        with self.runner.isolated_filesystem():
            with open("plan.json", "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "kind": "eagle-cli-plan",
                        "version": 1,
                        "operations": [
                            {
                                "kind": "bridge",
                                "action": "rename_items",
                                "payload": {"operations": [{"item_id": "abc", "new_name": "new"}]},
                            }
                        ],
                    },
                    handle,
                )
            result = self.runner.invoke(cli, ["--json", "plan", "apply", "plan.json"])
            self.assertEqual(result.exit_code, 0, result.output)
        mock_bridge_request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
