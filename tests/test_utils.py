import unittest

from cli_anything.eagle.utils.folders import find_folder_by_path, find_folders_by_name, flatten_folders
from cli_anything.eagle.utils.library import (
    find_smart_folder_by_path,
    flatten_smart_folders,
    summarize_smart_folder_rules,
    translate_smart_folder_to_item_filter,
)


class FolderUtilsTests(unittest.TestCase):
    def test_flatten_folders_builds_paths(self):
        records = flatten_folders(
            [{"id": "root", "name": "Root", "children": [{"id": "child", "name": "Child", "children": []}]}]
        )
        self.assertEqual([record.path for record in records], ["Root", "Root/Child"])

    def test_find_folder_by_path_matches_normalized_value(self):
        records = flatten_folders([{"id": "child", "name": "Child", "children": []}])
        match = find_folder_by_path(records, "/Child/")
        self.assertIsNotNone(match)
        self.assertEqual(match.id, "child")

    def test_find_folders_by_name_exact(self):
        records = flatten_folders(
            [
                {"id": "one", "name": "Inbox", "children": []},
                {"id": "two", "name": "inbox", "children": []},
            ]
        )
        matches = find_folders_by_name(records, "INBOX", exact=True)
        self.assertEqual(len(matches), 2)

    def test_flatten_smart_folders_builds_paths(self):
        records = flatten_smart_folders(
            [{"id": "root", "name": "Rules", "children": [{"id": "child", "name": "Images", "children": []}]}]
        )
        self.assertEqual([record.path for record in records], ["Rules", "Rules/Images"])

    def test_find_smart_folder_by_path_matches_normalized_value(self):
        records = flatten_smart_folders([{"id": "child", "name": "Images", "children": []}])
        match = find_smart_folder_by_path(records, "/Images/")
        self.assertIsNotNone(match)
        self.assertEqual(match.id, "child")

    def test_summarize_smart_folder_rules_counts_properties(self):
        records = flatten_smart_folders(
            [
                {
                    "id": "sf1",
                    "name": "PNG",
                    "children": [],
                    "conditions": [
                        {
                            "boolean": "TRUE",
                            "match": "AND",
                            "rules": [
                                {"property": "type", "method": "equal", "value": "png"},
                                {"property": "folders", "method": "intersection", "value": ["root"]},
                            ],
                        }
                    ],
                }
            ]
        )
        summary = summarize_smart_folder_rules(records)
        self.assertEqual(summary["rule_count"], 2)
        self.assertEqual(summary["properties"][0]["property"], "type")
        self.assertEqual(summary["methods"][0]["method"], "equal")

    def test_translate_smart_folder_to_item_filter_collects_supported_rules(self):
        records = flatten_smart_folders(
            [
                {
                    "id": "sf1",
                    "name": "PNG In Folder",
                    "children": [],
                    "conditions": [
                        {
                            "boolean": "TRUE",
                            "match": "AND",
                            "rules": [
                                {"property": "type", "method": "equal", "value": "png"},
                                {"property": "folders", "method": "intersection", "value": ["root"]},
                            ],
                        }
                    ],
                }
            ]
        )
        translation = translate_smart_folder_to_item_filter(records[0])
        self.assertTrue(translation["is_fully_supported"])
        self.assertEqual(translation["item_filter"]["ext"], "png")
        self.assertEqual(translation["item_filter"]["folders"], ["root"])

    def test_translate_smart_folder_to_item_filter_reports_unsupported_rules(self):
        records = flatten_smart_folders(
            [
                {
                    "id": "sf1",
                    "name": "Unsupported",
                    "children": [],
                    "conditions": [
                        {
                            "boolean": "TRUE",
                            "match": "OR",
                            "rules": [{"property": "type", "method": "equal", "value": "png"}],
                        }
                    ],
                }
            ]
        )
        translation = translate_smart_folder_to_item_filter(records[0])
        self.assertFalse(translation["is_fully_supported"])
        self.assertEqual(translation["unsupported_rule_count"], 1)


if __name__ == "__main__":
    unittest.main()
