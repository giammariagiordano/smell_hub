import unittest
from types import SimpleNamespace
from unittest.mock import patch

from analyzers.quality_metrics import QualityMetricsAnalyzer
from analyzers.traditional_smells import TraditionalSmellAnalyzer
from analyzers.vulnerabilities import BanditVulnerabilityAnalyzer
from api.main import _blame_line_info, _clone_repo_for_history, _is_vulnerability_analysis_enabled
from models.schemas import Project


class TestWindowsResilience(unittest.TestCase):
    def test_api_blame_handles_missing_stdout(self):
        with (
            patch("api.main.os.path.exists", return_value=True),
            patch("api.main.subprocess.run", return_value=SimpleNamespace(stdout=None)),
        ):
            self.assertIsNone(_blame_line_info("C:\\repo", "file.py", 10))

    def test_clone_repo_for_history_uses_default_temp_dir(self):
        with (
            patch("api.main.tempfile.mkdtemp", return_value="C:\\temp\\history_repo") as mkdtemp,
            patch("api.main.subprocess.run") as run,
        ):
            result = _clone_repo_for_history("C:\\repo")

        self.assertEqual(result, "C:\\temp\\history_repo")
        mkdtemp.assert_called_once_with(prefix="history_repo_")
        run.assert_called_once_with(
            ["git", "clone", "--quiet", "--no-checkout", "C:\\repo", "C:\\temp\\history_repo"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_quality_metrics_handles_none_source(self):
        metrics = QualityMetricsAnalyzer().analyze_file("demo.py", None)

        self.assertEqual(metrics["loc"], 0)
        self.assertEqual(metrics["nom"], 0)

    def test_traditional_blame_handles_missing_stdout(self):
        analyzer = TraditionalSmellAnalyzer(dpy_binary="C:\\tools\\DPy.exe")
        with (
            patch("analyzers.traditional_smells.os.path.exists", return_value=True),
            patch("analyzers.traditional_smells.subprocess.run", return_value=SimpleNamespace(stdout=None)),
        ):
            self.assertIsNone(analyzer._blame_author_email("C:\\repo", "file.py", 10))

    def test_vulnerability_blame_handles_missing_stdout(self):
        analyzer = BanditVulnerabilityAnalyzer()
        with (
            patch("analyzers.vulnerabilities.os.path.exists", return_value=True),
            patch("analyzers.vulnerabilities.subprocess.run", return_value=SimpleNamespace(stdout=None)),
        ):
            self.assertIsNone(analyzer._blame_author_email("C:\\repo", "file.py", 10))

    def test_vulnerability_analysis_flag_can_be_disabled(self):
        with patch.dict("os.environ", {"ANALYSIS_ENABLE_VULNERABILITIES": "false"}, clear=False):
            self.assertFalse(_is_vulnerability_analysis_enabled())

    def test_project_vulnerability_analysis_defaults_to_disabled(self):
        project = Project(id="p1", name="Demo", url="https://example.test/repo.git", local_path="C:\\repo")
        self.assertFalse(project.vulnerability_analysis_enabled)
        self.assertFalse(_is_vulnerability_analysis_enabled(project))

    def test_project_vulnerability_analysis_can_be_enabled_per_project(self):
        with patch.dict("os.environ", {"ANALYSIS_ENABLE_VULNERABILITIES": "false"}, clear=False):
            project = Project(
                id="p2",
                name="Demo",
                url="https://example.test/repo.git",
                local_path="C:\\repo",
                vulnerability_analysis_enabled=True,
            )
            self.assertTrue(_is_vulnerability_analysis_enabled(project))


if __name__ == "__main__":
    unittest.main()
