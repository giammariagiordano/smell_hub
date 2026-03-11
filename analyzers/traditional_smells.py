import json
import os
import re
import subprocess
import tempfile
from glob import glob
from typing import Dict, List, Optional, Set, Tuple

from models.schemas import SmellInstance


class TraditionalSmellAnalyzer:
    def __init__(self, dpy_binary: str):
        self.dpy_binary = dpy_binary

    @staticmethod
    def _smell_id(smell_name: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", (smell_name or "").strip().lower())
        return slug.strip("_") or "traditional_smell"

    @staticmethod
    def _parse_line(line_value: Optional[str]) -> Optional[int]:
        if not line_value:
            return None
        m = re.search(r"\d+", str(line_value))
        return int(m.group(0)) if m else None

    def _blame_author_email(self, repo_path: str, file_path: str, line: Optional[int]) -> Optional[str]:
        if not line:
            return None
        if not os.path.isabs(file_path):
            file_path = os.path.join(repo_path, file_path)
        if not os.path.exists(file_path):
            return None
        rel_file = os.path.relpath(file_path, repo_path)
        cmd = [
            "git", "-C", repo_path, "blame", "--line-porcelain",
            "-L", f"{line},{line}", rel_file
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        except Exception:
            return None
        for raw in res.stdout.splitlines():
            if raw.startswith("author-mail "):
                email = raw.split(" ", 1)[1].strip()
                email = email.strip("<>").lower()
                return email or None
        return None

    def _run_dpy(self, input_path: str, out_dir: str) -> Tuple[bool, str]:
        cmd = [
            self.dpy_binary, "analyze",
            "-i", input_path,
            "-o", out_dir,
            "-f", "json",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
            log_text = f"{res.stdout}\n{res.stderr}".lower()
            return True, log_text
        except subprocess.CalledProcessError as e:
            log_text = f"{e.stdout}\n{e.stderr}".lower()
            return False, log_text
        except subprocess.TimeoutExpired as e:
            log_text = f"{e.stdout}\n{e.stderr}".lower() if (e.stdout or e.stderr) else ""
            return False, log_text
        except Exception:
            return False, ""

    @staticmethod
    def _load_entries(out_dir: str) -> List[dict]:
        entries: List[dict] = []
        smell_files = []
        smell_files.extend(glob(os.path.join(out_dir, "*_implementation_smells.json")))
        smell_files.extend(glob(os.path.join(out_dir, "*_design_smells.json")))
        smell_files.extend(glob(os.path.join(out_dir, "*_arch_smells.json")))
        for filename in smell_files:
            if not os.path.exists(filename):
                continue
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            if isinstance(data, list):
                entries.extend([e for e in data if isinstance(e, dict)])
        return entries

    @staticmethod
    def _contains_python_code(path: str, max_dirs: int = 40) -> bool:
        if os.path.isfile(path):
            return path.endswith(".py")
        scanned = 0
        for _, _, files in os.walk(path):
            scanned += 1
            if scanned > max_dirs:
                break
            for f in files:
                if f.endswith(".py"):
                    return True
        return False

    def analyze_directory(
        self,
        project_root: str,
        email_to_dev_id: Optional[Dict[str, str]] = None
    ) -> List[SmellInstance]:
        if not os.path.exists(self.dpy_binary):
            return []

        with tempfile.TemporaryDirectory(prefix="dpy_", dir="/tmp") as out_dir:
            ok, log_text = self._run_dpy(project_root, out_dir)
            if not ok:
                return []

            entries = self._load_entries(out_dir)

            # DPy Trial: if full project exceeds LOC threshold, no detailed files.
            if not entries and "crossed the threshold" in log_text:
                max_shards = 12
                skipped = {
                    ".git", ".hg", ".svn", ".idea", ".vscode",
                    "node_modules", "dist", "build", "__pycache__",
                    ".venv", "venv", "env", ".mypy_cache", ".pytest_cache"
                }
                candidates: List[str] = []
                for name in sorted(os.listdir(project_root)):
                    if name.startswith("."):
                        continue
                    if name in skipped:
                        continue
                    sub_path = os.path.join(project_root, name)
                    if not self._contains_python_code(sub_path):
                        continue
                    candidates.append(sub_path)

                for sub_path in candidates[:max_shards]:
                    with tempfile.TemporaryDirectory(prefix="dpy_shard_", dir="/tmp") as shard_out:
                        shard_ok, _ = self._run_dpy(sub_path, shard_out)
                        if not shard_ok:
                            continue
                        entries.extend(self._load_entries(shard_out))

            smells: List[SmellInstance] = []
            seen: Set[Tuple[str, str, Optional[int], str]] = set()
            for entry in entries:
                    smell_name = str(entry.get("Smell") or "Traditional Smell")
                    file_path = str(entry.get("File") or "")
                    line_raw = str(entry.get("Line no") or "")
                    line = self._parse_line(line_raw)
                    detail = str(entry.get("Details") or "")
                    method = str(entry.get("Function/Method") or "")

                    author_id = None
                    if email_to_dev_id and file_path and line:
                        email = self._blame_author_email(project_root, file_path, line)
                        if email:
                            author_id = email_to_dev_id.get(email.lower())

                    affected = [author_id] if author_id else [file_path or method or "unknown"]
                    message = detail or f"{smell_name} detected."
                    if method:
                        message = f"{message} (method: {method})"

                    sig = (self._smell_id(smell_name), file_path, line, message)
                    if sig in seen:
                        continue
                    seen.add(sig)

                    smells.append(SmellInstance(
                        smell_id=self._smell_id(smell_name),
                        name=smell_name,
                        type="Code",
                        description=message,
                        affected_entities=affected,
                        file_path=file_path or None,
                        line=line,
                        message=message,
                        snippet=None,
                        refactoring_suggestion=None
                    ))
            return smells
