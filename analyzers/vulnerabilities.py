import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional

from models.schemas import VulnerabilityInstance


class BanditVulnerabilityAnalyzer:
    def __init__(self):
        self.bandit_bin = shutil.which("bandit")

    @staticmethod
    def _normalize_path(path: str, root_dir: str) -> str:
        if not path:
            return ""
        if os.path.isabs(path):
            return path
        return os.path.join(root_dir, path)

    @staticmethod
    def _slug(raw: str) -> str:
        return (raw or "").strip().lower().replace("-", "_").replace(" ", "_")

    @staticmethod
    def _python_cmd() -> List[str]:
        override = (os.environ.get("SMELLHUB_PYTHON_EXECUTABLE", "") or "").strip()
        if override:
            return [override]
        if sys.executable:
            return [sys.executable]
        fallback = shutil.which("python") or shutil.which("python3")
        return [fallback or "python"]

    def _blame_author_email(self, repo_path: str, file_path: str, line: Optional[int]) -> Optional[str]:
        if not line or not file_path:
            return None
        file_abs = self._normalize_path(file_path, repo_path)
        if not os.path.exists(file_abs):
            return None
        rel = os.path.relpath(file_abs, repo_path)
        cmd = [
            "git", "-C", repo_path, "blame", "--line-porcelain",
            "-L", f"{line},{line}", rel
        ]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
        except Exception:
            return None
        stdout = res.stdout or ""
        for row in stdout.splitlines():
            if row.startswith("author-mail "):
                return row.split(" ", 1)[1].strip().strip("<>").lower()
        return None

    def _run_bandit(self, root_dir: str, out_path: str) -> bool:
        base_cmd = []
        if self.bandit_bin:
            base_cmd = [self.bandit_bin]
        else:
            # Fallback to python module if executable is not in PATH.
            base_cmd = self._python_cmd() + ["-m", "bandit"]

        cmd = base_cmd + ["-r", root_dir, "-f", "json", "-o", out_path, "-q"]
        try:
            # Bandit returns non-zero when findings exist; ignore return code.
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=300,
            )
            return os.path.exists(out_path)
        except Exception:
            return False

    def analyze_directory(
        self,
        root_dir: str,
        email_to_dev_id: Optional[Dict[str, str]] = None
    ) -> List[VulnerabilityInstance]:
        with tempfile.TemporaryDirectory(prefix="bandit_") as tmp:
            report = os.path.join(tmp, "bandit.json")
            if not self._run_bandit(root_dir, report):
                return []
            try:
                with open(report, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                return []

        results = payload.get("results", []) if isinstance(payload, dict) else []
        vulns: List[VulnerabilityInstance] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            test_id = str(item.get("test_id") or "bandit_issue")
            test_name = str(item.get("test_name") or test_id)
            severity = str(item.get("issue_severity") or "UNSPECIFIED").upper()
            confidence = str(item.get("issue_confidence") or "UNSPECIFIED").upper()
            file_path = str(item.get("filename") or "")
            line_no = item.get("line_number")
            line = int(line_no) if isinstance(line_no, int) else None
            issue_text = str(item.get("issue_text") or "").strip()
            message = issue_text or f"{test_name} detected by Bandit."
            cwe = item.get("issue_cwe") or item.get("cwe")
            cwe_id = ""
            if isinstance(cwe, dict):
                cwe_id = str(cwe.get("id") or "")
            elif cwe is not None:
                cwe_id = str(cwe)

            author_id = None
            if email_to_dev_id and line and file_path:
                email = self._blame_author_email(root_dir, file_path, line)
                if email:
                    author_id = email_to_dev_id.get(email.lower())
            affected = [author_id] if author_id else [self._normalize_path(file_path, root_dir)]

            vulns.append(VulnerabilityInstance(
                vuln_id=self._slug(test_id),
                name=test_name,
                type="Vulnerability",
                severity=severity,
                confidence=confidence,
                description=message,
                affected_entities=affected,
                file_path=file_path or None,
                line=line,
                message=message,
                cwe=cwe_id or None,
                tool="Bandit"
            ))
        return vulns
