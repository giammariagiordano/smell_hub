import os
import tempfile
import unittest

from analyzers.ml_smells import MLSmellAnalyzer


class TestMLSmellsIntegration(unittest.TestCase):
    def setUp(self):
        self.project_root = "/Users/broke31/Desktop/tool"
        self.smell_ai_root = os.path.join(self.project_root, "smell_ai")
        self.analyzer = MLSmellAnalyzer(self.smell_ai_root)

    def test_detects_smells_on_codesmile_fixture(self):
        fixture_project = os.path.join(
            self.smell_ai_root, "input", "projects", "example"
        )
        smells = self.analyzer.analyze_directory(fixture_project, {})

        self.assertGreater(len(smells), 0, "Expected smells on CodeSmile fixture project")
        self.assertIn("CodeSmile executed", self.analyzer.last_status)
        self.assertIsNone(self.analyzer.last_error)
        self.assertGreater(len(self.analyzer.last_call_graph_nodes), 0)

    def test_zero_smells_is_not_an_error(self):
        with tempfile.TemporaryDirectory(prefix="ml_clean_", dir="/tmp") as tmp:
            clean_file = os.path.join(tmp, "clean.py")
            with open(clean_file, "w", encoding="utf-8") as f:
                f.write("def add(a, b):\n    return a + b\n")

            smells = self.analyzer.analyze_directory(tmp, {})

            self.assertEqual(len(smells), 0)
            self.assertIn("CodeSmile executed", self.analyzer.last_status)
            self.assertIsNone(
                self.analyzer.last_error,
                f"Zero-smell run must not be treated as an error: {self.analyzer.last_status}",
            )


if __name__ == "__main__":
    unittest.main()
