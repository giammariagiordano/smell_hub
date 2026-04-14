import os
import tempfile
import unittest

from api.main import _discover_git_repositories, _expand_bulk_repo_items
from api.main import BulkRepoItem


class TestPathImportDiscovery(unittest.TestCase):
    def test_discover_git_repositories_recursively(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_a = os.path.join(tmp, "repo-a")
            repo_b = os.path.join(tmp, "nested", "repo-b")
            os.makedirs(os.path.join(repo_a, ".git"))
            os.makedirs(os.path.join(repo_b, ".git"))

            discovered = _discover_git_repositories(tmp)

            self.assertEqual(
                discovered,
                sorted([os.path.abspath(repo_a), os.path.abspath(repo_b)]),
            )

    def test_expand_bulk_repo_items_from_parent_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_a = os.path.join(tmp, "repo-a")
            repo_b = os.path.join(tmp, "repo-b")
            os.makedirs(os.path.join(repo_a, ".git"))
            os.makedirs(os.path.join(repo_b, ".git"))

            expanded = _expand_bulk_repo_items(
                [BulkRepoItem(url="", name="ignored", local_path=tmp, vulnerability_analysis_enabled=True)]
            )

            self.assertEqual(len(expanded), 2)
            self.assertEqual(
                {os.path.abspath(item.local_path or "") for item in expanded},
                {os.path.abspath(repo_a), os.path.abspath(repo_b)},
            )
            self.assertTrue(all(item.vulnerability_analysis_enabled for item in expanded))
            self.assertEqual({item.name for item in expanded}, {"repo-a", "repo-b"})

    def test_expand_bulk_repo_items_keeps_single_repo_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_a = os.path.join(tmp, "repo-a")
            os.makedirs(os.path.join(repo_a, ".git"))

            expanded = _expand_bulk_repo_items(
                [BulkRepoItem(url="", name="custom-name", local_path=repo_a, vulnerability_analysis_enabled=False)]
            )

            self.assertEqual(len(expanded), 1)
            self.assertEqual(os.path.abspath(expanded[0].local_path or ""), os.path.abspath(repo_a))
            self.assertEqual(expanded[0].name, "custom-name")


if __name__ == "__main__":
    unittest.main()
