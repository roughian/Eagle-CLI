import json
import unittest
from pathlib import Path
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
    @patch("cli_anything.eagle.eagle_cli.bridge_health")
    def test_bridge_status_reports_health_summary(self, mock_bridge_health, mock_load, _mock_save):
        from cli_anything.eagle import __version__
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_bridge_health.return_value = {
            "template_dir": "/tmp/template",
            "template_exists": True,
            "layout": {
                "state_dir": "/tmp/state",
                "requests": "/tmp/requests",
                "responses": "/tmp/responses",
                "processed": "/tmp/processed",
            },
            "status_path": "/tmp/state/status.json",
            "installed_plugin_paths": ["/tmp/plugins/example"],
            "default_plugin_dirs": ["/tmp/plugins"],
            "health": "healthy",
            "heartbeat_age_seconds": 1.25,
            "queue_depth": 0,
            "pending_request_count": 0,
            "pending_response_count": 0,
            "processed_count": 2,
            "writable": {"state_dir": True, "requests": True, "responses": True, "processed": True},
            "status_error": None,
            "plugin_version": __version__,
            "status": {"updatedAt": "2026-04-02T00:00:00+00:00"},
        }
        result = self.runner.invoke(cli, ["--json", "bridge", "status"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["health"], "healthy")
        self.assertFalse(payload["data"]["version_mismatch"])
        self.assertEqual(payload["data"]["pending_request_count"], 0)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli._bridge_ping_probe")
    @patch("cli_anything.eagle.eagle_cli.bridge_health")
    def test_bridge_doctor_reports_warning_when_ping_times_out(
        self, mock_bridge_health, mock_ping_probe, mock_load, _mock_save
    ):
        from cli_anything.eagle import __version__
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_bridge_health.return_value = {
            "template_dir": "/tmp/template",
            "template_exists": True,
            "layout": {
                "state_dir": "/tmp/state",
                "requests": "/tmp/requests",
                "responses": "/tmp/responses",
                "processed": "/tmp/processed",
            },
            "status_path": "/tmp/state/status.json",
            "installed_plugin_paths": ["/tmp/plugins/example"],
            "default_plugin_dirs": ["/tmp/plugins"],
            "health": "stale",
            "heartbeat_age_seconds": 45.0,
            "queue_depth": 1,
            "pending_request_count": 1,
            "pending_response_count": 0,
            "processed_count": 5,
            "writable": {"state_dir": True, "requests": True, "responses": True, "processed": True},
            "status_error": None,
            "plugin_version": __version__,
            "status": {"updatedAt": "2026-04-02T00:00:00+00:00"},
        }
        mock_ping_probe.return_value = {"status": "timeout", "error": "Timed out waiting for ping"}
        result = self.runner.invoke(cli, ["--json", "bridge", "doctor", "--timeout", "1"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "warning")
        self.assertFalse(payload["data"]["ready"])
        self.assertTrue(any(check["name"] == "ping" and not check["ok"] for check in payload["data"]["checks"]))

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.prune_bridge_files")
    def test_bridge_cleanup_dry_run_reports_candidates(self, mock_prune_bridge_files, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_prune_bridge_files.return_value = {
            "max_age_seconds": 3600.0,
            "keep_last": 20,
            "dry_run": True,
            "groups": {
                "responses": {
                    "examined_count": 4,
                    "kept_count": 3,
                    "candidates": [{"path": "/tmp/responses/old.json", "age_seconds": 7200.0, "deleted": False}],
                }
            },
            "candidate_count": 1,
            "deleted_count": 0,
        }
        result = self.runner.invoke(cli, ["--json", "--dry-run", "bridge", "cleanup", "--max-age-hours", "1"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "dry-run")
        self.assertEqual(payload["data"]["candidate_count"], 1)
        mock_prune_bridge_files.assert_called_once_with(
            max_age_seconds=3600.0,
            keep_last=20,
            include_requests=False,
            include_responses=True,
            include_processed=True,
            dry_run=True,
        )

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli._bridge_request")
    def test_bridge_context_flattens_plugin_response(self, mock_bridge_request, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_bridge_request.return_value = {
            "status": "success",
            "data": {
                "request_id": "req-1",
                "response": {
                    "status": "success",
                    "data": {
                        "item_limit": 5,
                        "selected_item_count": 2,
                        "selected_folder_count": 1,
                        "truncated_items": False,
                        "selected_items": [{"id": "a", "name": "Alpha"}],
                        "selected_folders": [{"id": "root", "name": "Root"}],
                    },
                },
            },
        }
        result = self.runner.invoke(cli, ["--json", "bridge", "context", "--item-limit", "5"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["request_id"], "req-1")
        self.assertEqual(payload["data"]["selected_item_count"], 2)
        self.assertEqual(payload["data"]["selected_folders"][0]["id"], "root")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli._bridge_request")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.folder_list")
    def test_bridge_open_folder_resolves_path_and_calls_bridge(self, mock_folder_list, mock_bridge_request, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_folder_list.return_value = {
            "status": "success",
            "data": [{"id": "root", "name": "Root", "children": [{"id": "child", "name": "Child", "children": []}]}],
        }
        mock_bridge_request.return_value = {
            "status": "success",
            "data": {
                "request_id": "req-folder",
                "response": {"status": "success", "data": {"opened": True, "folder_id": "child"}},
            },
        }
        result = self.runner.invoke(cli, ["--json", "bridge", "open-folder", "--folder-path", "Root/Child"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["folder"]["id"], "child")
        self.assertEqual(mock_bridge_request.call_args.args[0], "open_folder")
        self.assertEqual(mock_bridge_request.call_args.args[1], {"folder_id": "child"})

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli._bridge_request")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_bridge_select_items_sends_resolved_item_ids(self, mock_item_info, mock_bridge_request, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.side_effect = [
            {"status": "success", "data": {"id": "abc", "name": "A"}},
            {"status": "success", "data": {"id": "def", "name": "B"}},
        ]
        mock_bridge_request.return_value = {
            "status": "success",
            "data": {
                "request_id": "req-select",
                "response": {
                    "status": "success",
                    "data": {"selected": True, "selected_count": 2, "item_ids": ["abc", "def"]},
                },
            },
        }
        result = self.runner.invoke(cli, ["--json", "bridge", "select-items", "--item-id", "abc", "--item-id", "def"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["matched_count"], 2)
        self.assertEqual(payload["data"]["selected_count"], 2)
        self.assertEqual(mock_bridge_request.call_args.args[0], "select_items")
        self.assertEqual(mock_bridge_request.call_args.args[1], {"item_ids": ["abc", "def"]})

    @patch("cli_anything.eagle.eagle_cli.DEFAULT_STATE_DIR", Path(".state"))
    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli._bridge_request")
    def test_select_save_current_persists_bridge_selection(self, mock_bridge_request, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_bridge_request.return_value = {
            "status": "success",
            "data": {
                "request_id": "req-current",
                "response": {
                    "status": "success",
                    "data": {
                        "selected_item_count": 2,
                        "selected_folder_count": 1,
                        "truncated_items": False,
                        "selected_items": [{"id": "a"}, {"id": "b"}],
                        "selected_folders": [{"id": "root"}],
                    },
                },
            },
        }
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, ["--json", "select", "save-current", "active"])
            self.assertEqual(result.exit_code, 0, result.output)
            with open(".state/selections/active.json", "r", encoding="utf-8") as handle:
                saved = json.load(handle)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["item_count"], 2)
        self.assertEqual(saved["item_ids"], ["a", "b"])

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli._bridge_request")
    def test_item_selected_reads_bridge_context(self, mock_bridge_request, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_bridge_request.return_value = {
            "status": "success",
            "data": {
                "request_id": "req-items",
                "response": {
                    "status": "success",
                    "data": {
                        "selected_item_count": 2,
                        "truncated_items": False,
                        "selected_items": [{"id": "a", "name": "Alpha"}, {"id": "b", "name": "Beta"}],
                    },
                },
            },
        }
        result = self.runner.invoke(cli, ["--json", "item", "selected", "--item-limit", "5"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["selected_item_count"], 2)
        self.assertEqual(payload["data"]["items"][1]["id"], "b")
        mock_bridge_request.assert_called_once_with("get_context", {"item_limit": 5}, timeout_seconds=15.0, queue_only=False)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.folder_list")
    @patch("cli_anything.eagle.eagle_cli._bridge_request")
    def test_folder_selected_resolves_paths_from_bridge_context(self, mock_bridge_request, mock_folder_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_folder_list.return_value = {
            "status": "success",
            "data": [{"id": "root", "name": "Root", "children": [{"id": "child", "name": "Child", "children": []}]}],
        }
        mock_bridge_request.return_value = {
            "status": "success",
            "data": {
                "request_id": "req-folders",
                "response": {
                    "status": "success",
                    "data": {
                        "selected_folder_count": 1,
                        "selected_folders": [{"id": "child", "name": "Child", "parent": "root"}],
                    },
                },
            },
        }
        result = self.runner.invoke(cli, ["--json", "folder", "selected"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["folders"][0]["path"], "Root/Child")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    @patch("cli_anything.eagle.eagle_cli._bridge_request")
    def test_item_open_calls_bridge_with_selected_ids(self, mock_bridge_request, mock_item_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.return_value = {"status": "success", "data": {"id": "abc", "name": "Sample"}}
        mock_bridge_request.return_value = {
            "status": "success",
            "data": {
                "request_id": "req-open",
                "response": {"status": "success", "data": {"opened": True, "opened_count": 1}},
            },
        }
        result = self.runner.invoke(cli, ["--json", "item", "open", "--item-id", "abc", "--window"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["matched_count"], 1)
        mock_bridge_request.assert_called_once_with(
            "open_items",
            {"item_ids": ["abc"], "window": True},
            timeout_seconds=15.0,
            queue_only=False,
        )

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli._bridge_request")
    def test_tag_rename_live_calls_bridge(self, mock_bridge_request, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_bridge_request.return_value = {
            "status": "success",
            "data": {"request_id": "req-tag-rename", "response": {"status": "success", "data": {"renamed": True}}},
        }
        result = self.runner.invoke(cli, ["--json", "tag", "rename-live", "Old", "New"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["source"], "Old")
        mock_bridge_request.assert_called_once_with(
            "rename_tag",
            {"source": "Old", "target": "New"},
            timeout_seconds=15.0,
            queue_only=False,
        )

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli._bridge_request")
    def test_tag_merge_live_calls_bridge(self, mock_bridge_request, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_bridge_request.return_value = {
            "status": "success",
            "data": {"request_id": "req-tag-merge", "response": {"status": "success", "data": {"affectedItems": 3}}},
        }
        result = self.runner.invoke(cli, ["--json", "tag", "merge-live", "Legacy", "Canonical"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["target"], "Canonical")
        mock_bridge_request.assert_called_once_with(
            "merge_tags",
            {"source": "Legacy", "target": "Canonical"},
            timeout_seconds=15.0,
            queue_only=False,
        )

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

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_tag_normalize_dry_run_builds_operations(self, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_list.return_value = {
            "status": "success",
            "data": [{"id": "abc", "name": "Sample", "tags": ["  UI  ", "mobile   app"]}],
        }
        result = self.runner.invoke(cli, ["--json", "--dry-run", "tag", "normalize", "--all", "--trim", "--collapse-spaces"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "dry-run")
        self.assertEqual(payload["data"]["operations"][0]["payload"]["tags"], ["UI", "mobile app"])

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_select_save_and_diff_uses_selection_state(self, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_list.side_effect = [
            {"status": "success", "data": [{"id": "a"}, {"id": "b"}]},
            {"status": "success", "data": [{"id": "b"}, {"id": "c"}]},
        ]
        with self.runner.isolated_filesystem():
            with patch("cli_anything.eagle.eagle_cli.DEFAULT_STATE_DIR", Path("state")):
                first = self.runner.invoke(cli, ["--json", "select", "save", "left", "--keyword", "left"])
                second = self.runner.invoke(cli, ["--json", "select", "save", "right", "--keyword", "right"])
                diff = self.runner.invoke(cli, ["--json", "select", "diff", "left", "right"])
            self.assertEqual(first.exit_code, 0, first.output)
            self.assertEqual(second.exit_code, 0, second.output)
            self.assertEqual(diff.exit_code, 0, diff.output)
            payload = json.loads(diff.output)
            self.assertEqual(payload["data"]["left_only"], ["a"])
            self.assertEqual(payload["data"]["right_only"], ["c"])
            self.assertEqual(payload["data"]["common"], ["b"])

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_report_trend_writes_markdown(self, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_list.return_value = {"status": "success", "data": [{"id": "a", "mtime": 1704067200000}]}
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, ["--json", "report", "trend", "trend.md", "--all"])
            self.assertEqual(result.exit_code, 0, result.output)
            with open("trend.md", "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("# CLI-Anything Eagle Trend Report", content)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_plan_merge_and_validate(self, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        with self.runner.isolated_filesystem():
            with open("one.json", "w", encoding="utf-8") as handle:
                json.dump({"kind": "eagle-cli-plan", "version": 1, "operations": [{"method": "POST", "endpoint": "/api/item/update"}]}, handle)
            with open("two.json", "w", encoding="utf-8") as handle:
                json.dump({"kind": "eagle-cli-plan", "version": 1, "operations": [{"kind": "bridge", "action": "rename_items", "payload": {"operations": []}}]}, handle)
            merged = self.runner.invoke(cli, ["--json", "plan", "merge", "merged.json", "one.json", "two.json"])
            validated = self.runner.invoke(cli, ["--json", "plan", "validate", "merged.json"])
            self.assertEqual(merged.exit_code, 0, merged.output)
            self.assertEqual(validated.exit_code, 0, validated.output)
            payload = json.loads(validated.output)
            self.assertTrue(payload["data"]["valid"])
            self.assertEqual(payload["data"]["operation_count"], 2)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_plan_rollback_from_results_builds_restore_plan(self, mock_item_info, mock_load, _mock_save):
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
                        "items": [{"id": "abc", "name": "Saved", "tags": ["ui"], "annotation": "", "url": "", "folders": ["new-folder"]}],
                    },
                    handle,
                )
            with open("results.json", "w", encoding="utf-8") as handle:
                json.dump({"status": "success", "data": {"saved_snapshot": "snap.json"}}, handle)
            result = self.runner.invoke(cli, ["--json", "plan", "rollback-from-results", "rollback.json", "results.json"])
            self.assertEqual(result.exit_code, 0, result.output)
            with open("rollback.json", "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(len(payload["operations"]), 3)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_workflow_validate_reports_invalid_steps(self, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        with self.runner.isolated_filesystem():
            with open("workflow.json", "w", encoding="utf-8") as handle:
                json.dump({"kind": "eagle-cli-workflow", "steps": [{"action": "bad-action"}]}, handle)
            result = self.runner.invoke(cli, ["--json", "workflow", "validate", "workflow.json"])
            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertFalse(payload["data"]["valid"])

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_workflow_run_dry_run_saves_plan(self, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_list.return_value = {"status": "success", "data": [{"id": "abc", "name": "Sample", "tags": ["old"], "folders": []}]}
        with self.runner.isolated_filesystem():
            with open("workflow.json", "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "kind": "eagle-cli-workflow",
                        "selection": {"keyword": "ui"},
                        "steps": [
                            {"action": "bulk-update", "add_tags": ["reviewed"]},
                            {"action": "rename", "prefix": "new-"},
                        ],
                    },
                    handle,
                )
            result = self.runner.invoke(cli, ["--json", "--dry-run", "workflow", "run", "workflow.json", "--save-plan", "workflow-plan.json"])
            self.assertEqual(result.exit_code, 0, result.output)
            with open("workflow-plan.json", "r", encoding="utf-8") as handle:
                plan = json.load(handle)
            self.assertEqual(len(plan["operations"]), 2)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_ingest_manifest_dry_run_uses_manifest_items(self, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        with self.runner.isolated_filesystem():
            with open("manifest.json", "w", encoding="utf-8") as handle:
                json.dump({"items": [{"path": "/tmp/demo.png", "name": "demo"}]}, handle)
            result = self.runner.invoke(cli, ["--json", "--dry-run", "ingest", "manifest", "manifest.json"])
            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(len(payload["data"]["payload"]["items"]), 1)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_add_from_paths")
    def test_watch_import_dir_tracks_changed_files(self, mock_add_from_paths, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_add_from_paths.return_value = {"status": "success", "data": {"itemIds": ["abc"]}}
        with self.runner.isolated_filesystem():
            Path("assets").mkdir()
            Path("assets/demo.png").write_text("demo", encoding="utf-8")
            first = self.runner.invoke(cli, ["--json", "watch", "import-dir", "assets", "--state-file", "watch.json"])
            second = self.runner.invoke(cli, ["--json", "watch", "import-dir", "assets", "--state-file", "watch.json"])
            self.assertEqual(first.exit_code, 0, first.output)
            self.assertEqual(second.exit_code, 0, second.output)
            first_payload = json.loads(first.output)
            second_payload = json.loads(second.output)
            self.assertEqual(first_payload["data"]["changed_count"], 1)
            self.assertEqual(second_payload["data"]["changed_count"], 0)
            self.assertEqual(mock_add_from_paths.call_count, 1)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_completion_script_and_schema_show_emit_documents(self, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        with self.runner.isolated_filesystem():
            completion_result = self.runner.invoke(cli, ["--json", "completion", "script", "--shell", "zsh", "--output", "completion.sh"])
            schema_result = self.runner.invoke(cli, ["--json", "schema", "show", "workflow", "--output", "schema.json"])
            self.assertEqual(completion_result.exit_code, 0, completion_result.output)
            self.assertEqual(schema_result.exit_code, 0, schema_result.output)
            self.assertTrue(Path("completion.sh").exists())
            self.assertTrue(Path("schema.json").exists())

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_workflow_validate_accepts_valid_document(self, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        with self.runner.isolated_filesystem():
            with open("workflow.json", "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "kind": "eagle-cli-workflow",
                        "version": 1,
                        "selection": {"item_ids": ["abc"]},
                        "steps": [{"action": "snapshot", "output": "snap.json"}],
                    },
                    handle,
                )
            result = self.runner.invoke(cli, ["--json", "workflow", "validate", "workflow.json"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertTrue(payload["data"]["valid"])

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_workflow_run_dry_run_reports_steps(self, mock_item_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.return_value = {
            "status": "success",
            "data": {"id": "abc", "name": "Sample", "tags": ["ui"], "folders": ["f1"]},
        }
        with self.runner.isolated_filesystem():
            with open("workflow.json", "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "kind": "eagle-cli-workflow",
                        "version": 1,
                        "selection": {"item_ids": ["abc"]},
                        "steps": [
                            {"action": "snapshot", "output": "snap.json"},
                            {"action": "export-items", "output": "items.jsonl", "format": "jsonl"},
                        ],
                    },
                    handle,
                )
            result = self.runner.invoke(cli, ["--json", "--dry-run", "workflow", "run", "workflow.json"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "dry-run")
        self.assertEqual(payload["data"]["item_count"], 1)
        self.assertEqual(payload["data"]["steps"][0]["action"], "snapshot")
        self.assertEqual(payload["data"]["steps"][1]["format"], "jsonl")

    @patch("cli_anything.eagle.eagle_cli.DEFAULT_STATE_DIR", Path(".state"))
    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_select_save_and_diff_persist_selection_sets(self, mock_item_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()

        def item_info(item_id):
            return {"status": "success", "data": {"id": item_id, "name": item_id.upper(), "tags": []}}

        mock_item_info.side_effect = item_info
        with self.runner.isolated_filesystem():
            result_alpha = self.runner.invoke(cli, ["--json", "select", "save", "alpha", "--item-id", "a", "--item-id", "b"])
            self.assertEqual(result_alpha.exit_code, 0, result_alpha.output)
            result_beta = self.runner.invoke(cli, ["--json", "select", "save", "beta", "--item-id", "b", "--item-id", "c"])
            self.assertEqual(result_beta.exit_code, 0, result_beta.output)
            result_diff = self.runner.invoke(cli, ["--json", "select", "diff", "alpha", "beta"])
        self.assertEqual(result_diff.exit_code, 0, result_diff.output)
        payload = json.loads(result_diff.output)
        self.assertEqual(payload["data"]["common"], ["b"])
        self.assertEqual(payload["data"]["left_only"], ["a"])
        self.assertEqual(payload["data"]["right_only"], ["c"])

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_report_tags_summarizes_tag_counts(self, mock_item_list, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_list.return_value = {
            "status": "success",
            "data": [
                {"id": "a", "name": "One", "tags": ["ui", "design"]},
                {"id": "b", "name": "Two", "tags": ["ui"]},
                {"id": "c", "name": "Three", "tags": []},
            ],
        }
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, ["--json", "report", "tags", "tags.json", "--all", "--top", "1"])
            self.assertEqual(result.exit_code, 0, result.output)
            with open("tags.json", "r", encoding="utf-8") as handle:
                report = json.load(handle)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["row_count"], 1)
        self.assertEqual(report["rows"][0]["tag"], "ui")

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_info")
    def test_tag_normalize_dry_run_builds_normalized_tags(self, mock_item_info, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_info.return_value = {
            "status": "success",
            "data": {"id": "abc", "name": "Sample", "tags": ["  UI  ", "UI", "Design"]},
        }
        result = self.runner.invoke(
            cli,
            ["--json", "--dry-run", "tag", "normalize", "--item-id", "abc", "--lowercase", "--trim", "--collapse-spaces"],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["data"]["operation_count"], 1)
        self.assertEqual(payload["data"]["operations"][0]["payload"]["tags"], ["ui", "design"])

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_watch_import_dir_dry_run_detects_changed_files(self, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        with self.runner.isolated_filesystem():
            source_dir = Path("watch-source")
            nested_dir = source_dir / "nested"
            nested_dir.mkdir(parents=True)
            (nested_dir / "image.png").write_bytes(b"png")
            result = self.runner.invoke(
                cli,
                [
                    "--json",
                    "--dry-run",
                    "watch",
                    "import-dir",
                    str(source_dir),
                    "--recursive",
                    "--tag-from-path",
                    "--tag-from-name",
                    "--name-template",
                    "{stem}-{index}",
                ],
            )
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "dry-run")
        self.assertEqual(payload["data"]["changed_count"], 1)
        self.assertEqual(payload["data"]["items"][0]["name"], "image-1")
        self.assertIn("nested", payload["data"]["items"][0]["tags"])
        self.assertIn("image", payload["data"]["items"][0]["tags"])

    def test_config_surface_is_ready_for_completion_expansion(self):
        config_group = cli.commands.get("config")
        if config_group is None:
            self.skipTest("config commands are not implemented yet")

        self.assertTrue({"show", "set", "unset", "path"}.issubset(set(config_group.commands)))
        result = self.runner.invoke(cli, ["config", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        for command_name in ["show", "set", "unset", "path"]:
            self.assertIn(command_name, result.output)

    def test_report_dashboard_surface_is_ready_for_completion_expansion(self):
        report_group = cli.commands.get("report")
        if report_group is None or "dashboard" not in report_group.commands:
            self.skipTest("report dashboard is not implemented yet")

        result = self.runner.invoke(cli, ["report", "dashboard", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("dashboard", result.output)

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    def test_config_set_show_unset_persists_defaults(self, mock_load, _mock_save):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        with self.runner.isolated_filesystem():
            config_path = Path("state/config.json")
            with patch("cli_anything.eagle.core.config.DEFAULT_CONFIG_PATH", config_path):
                result_set = self.runner.invoke(cli, ["--json", "config", "set", "report_format", "md"])
                self.assertEqual(result_set.exit_code, 0, result_set.output)
                result_show = self.runner.invoke(cli, ["--json", "config", "show"])
                self.assertEqual(result_show.exit_code, 0, result_show.output)
                result_key = self.runner.invoke(cli, ["--json", "config", "show", "--key", "report_format"])
                self.assertEqual(result_key.exit_code, 0, result_key.output)
                result_unset = self.runner.invoke(cli, ["--json", "config", "unset", "report_format"])
                self.assertEqual(result_unset.exit_code, 0, result_unset.output)

            with open(config_path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
        payload_show = json.loads(result_show.output)
        payload_key = json.loads(result_key.output)
        payload_unset = json.loads(result_unset.output)
        self.assertEqual(saved["defaults"], {})
        self.assertEqual(payload_show["data"]["defaults"]["report_format"], "md")
        self.assertEqual(payload_key["data"]["value"], "md")
        self.assertTrue(payload_unset["data"]["removed"])

    @patch("cli_anything.eagle.eagle_cli.SessionState.save")
    @patch("cli_anything.eagle.eagle_cli.SessionState.load")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.folder_list")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.library_info")
    @patch("cli_anything.eagle.eagle_cli.EagleClient.item_list")
    def test_report_dashboard_and_completion_use_config_defaults(
        self,
        mock_item_list,
        mock_library_info,
        mock_folder_list,
        mock_load,
        _mock_save,
    ):
        from cli_anything.eagle.core.state import SessionState

        mock_load.return_value = SessionState()
        mock_item_list.return_value = {
            "status": "success",
            "data": [
                {"id": "a", "name": "One", "tags": ["ui"], "folders": ["child"], "ext": "png", "mtime": 1710000000000},
                {"id": "b", "name": "Two", "tags": ["ui", "design"], "folders": [], "ext": "jpg", "mtime": 1711000000000},
            ],
        }
        mock_library_info.return_value = {
            "status": "success",
            "data": {
                "library": {"name": "Demo", "path": "/tmp/demo.library"},
                "applicationVersion": "4.0.0",
                "folders": [{"id": "root", "name": "Root", "children": [{"id": "child", "name": "Child", "children": []}]}],
                "smartFolders": [],
                "quickAccess": [{"id": "qa", "name": "Recent", "type": "shortcut"}],
                "tagsGroups": [],
            },
        }
        mock_folder_list.return_value = {
            "status": "success",
            "data": [{"id": "root", "name": "Root", "children": [{"id": "child", "name": "Child", "children": []}]}],
        }
        with self.runner.isolated_filesystem():
            config_path = Path("state/config.json")
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "defaults": {
                            "report_format": "md",
                            "completion_shell": "fish",
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            with patch("cli_anything.eagle.core.config.DEFAULT_CONFIG_PATH", config_path):
                result_dashboard = self.runner.invoke(cli, ["--json", "report", "dashboard", "dashboard.out", "--all", "--top", "2"])
                self.assertEqual(result_dashboard.exit_code, 0, result_dashboard.output)
                result_completion = self.runner.invoke(cli, ["--json", "completion", "script", "--output", "completion.txt"])
                self.assertEqual(result_completion.exit_code, 0, result_completion.output)
                dashboard_text = Path("dashboard.out").read_text(encoding="utf-8")
                completion_text = Path("completion.txt").read_text(encoding="utf-8")
        payload_dashboard = json.loads(result_dashboard.output)
        payload_completion = json.loads(result_completion.output)
        self.assertEqual(payload_dashboard["data"]["format"], "md")
        self.assertIn("CLI-Anything Eagle Dashboard", dashboard_text)
        self.assertEqual(payload_completion["data"]["shell"], "fish")
        self.assertIn("fish_source", completion_text)


if __name__ == "__main__":
    unittest.main()
