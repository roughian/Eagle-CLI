import unittest

from cli_anything.eagle.utils.folders import find_folder_by_path, find_folders_by_name, flatten_folders


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


if __name__ == "__main__":
    unittest.main()
