import os
import tempfile
import unittest
from unittest.mock import patch

from analyzers.ml_smells import MLSmellAnalyzer


class TestMLSmellsIntegration(unittest.TestCase):
    def setUp(self):
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
        with tempfile.TemporaryDirectory(prefix="ml_clean_") as tmp:
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

    def test_codesmile_wrapper_enables_parallel_workers(self):
        with tempfile.TemporaryDirectory(prefix="ml_parallel_") as tmp:
            with patch.dict(
                os.environ, {"SMELLHUB_CODESMILE_WORKERS": "12"}, clear=False
            ):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value.returncode = 0
                    mock_run.return_value.stdout = ""
                    mock_run.return_value.stderr = ""

                    ok = self.analyzer._run_smell_ai(tmp, tmp)

            self.assertTrue(ok)
            invoked_cmd = mock_run.call_args.args[0]
            self.assertIn("--parallel", invoked_cmd)
            self.assertIn("--max_walkers", invoked_cmd)
            self.assertIn("12", invoked_cmd)


if __name__ == "__main__":
    unittest.main()
