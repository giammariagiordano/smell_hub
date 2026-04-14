import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional

from models.schemas import SmellInstance


class MLSmellAnalyzer:
    def __init__(self, smell_ai_root: Optional[str] = None):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.smell_ai_root = smell_ai_root or os.path.join(project_root, "smell_ai")
        self.last_status: str = "Not started"
        self.last_error: Optional[str] = None
        self.last_stdout: str = ""
        self.last_stderr: str = ""
        self.last_call_graph_nodes: List[Dict[str, object]] = []
        self.last_call_graph_edges: List[Dict[str, object]] = []

    @staticmethod
    def _to_int(value: str) -> Optional[int]:
        try:
            return int(str(value).strip())
        except Exception:
            return None

    @staticmethod
    def _smell_id(raw: str) -> str:
        return (raw or "").strip().upper().replace(" ", "_")

    @staticmethod
    def _python_cmd() -> List[str]:
        override = (os.environ.get("SMELLHUB_PYTHON_EXECUTABLE", "") or "").strip()
        if override:
            return [override]
        if sys.executable:
            return [sys.executable]
        fallback = shutil.which("python") or shutil.which("python3")
        return [fallback or "python"]

    @classmethod
    def _codesmile_workers(cls) -> int:
        env_value = (
            os.environ.get("SMELLHUB_CODESMILE_WORKERS", "")
            or os.environ.get("CODESMILE_MAX_WORKERS", "")
        )
        parsed = cls._to_int(env_value) if env_value else None
        if parsed and parsed > 0:
            return parsed
        return max(1, os.cpu_count() or 1)

    def _run_smell_ai(self, input_dir: str, output_dir: str) -> bool:
        if not os.path.isdir(self.smell_ai_root):
            self.last_status = "CodeSmile directory not found"
            self.last_error = f"Missing directory: {self.smell_ai_root}"
            return False
        worker_count = self._codesmile_workers()
        cmd = self._python_cmd() + [
            "-m",
            "cli.cli_runner",
            "--input",
            input_dir,
            "--output",
            output_dir,
            "--call-graph",
        ]
        if worker_count > 1:
            cmd.extend(["--parallel", "--max_walkers", str(worker_count)])
        try:
            result = subprocess.run(
                cmd,
                cwd=self.smell_ai_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=600,
            )
            self.last_stdout = result.stdout or ""
            self.last_stderr = result.stderr or ""
            # We trust produced output files more than exit code for robustness.
            if result.returncode not in (0,):
                self.last_status = f"CodeSmile exited with code {result.returncode}"
                self.last_error = (self.last_stderr or self.last_stdout or "").strip()[:800] or None
            else:
                self.last_status = "CodeSmile executed"
            return True
        except Exception as e:
            self.last_status = "CodeSmile execution failed"
            self.last_error = str(e)
            return False

    def _load_call_graph(self, out_dir: str) -> None:
        self.last_call_graph_nodes = []
        self.last_call_graph_edges = []
        graph_path = os.path.join(out_dir, "output", "call_graph.json")
        if not os.path.exists(graph_path):
            return
        try:
            with open(graph_path, "r", encoding="utf-8", errors="ignore") as f:
                payload = json.load(f)
        except Exception:
            return
        nodes = payload.get("nodes", []) if isinstance(payload, dict) else []
        links = payload.get("links", []) if isinstance(payload, dict) else []
        parsed_nodes: List[Dict[str, object]] = []
        parsed_edges: List[Dict[str, object]] = []

        for n in nodes:
            if not isinstance(n, dict):
                continue
            node_id = str(n.get("id", ""))
            if not node_id:
                continue
            parsed_nodes.append({
                "id": node_id,
                "label": node_id.split("::")[-1] if "::" in node_id else node_id,
                "file": n.get("file"),
                "type": n.get("type"),
                "start_line": n.get("start_line"),
                "end_line": n.get("end_line"),
            })

        for e in links:
            if not isinstance(e, dict):
                continue
            src = str(e.get("source", ""))
            dst = str(e.get("target", ""))
            if not src or not dst:
                continue
            parsed_edges.append({"from": src, "to": dst})

        self.last_call_graph_nodes = parsed_nodes
        self.last_call_graph_edges = parsed_edges

    def analyze_directory(
        self,
        root_dir: str,
        file_author_map: Optional[Dict[str, str]] = None
    ) -> List[SmellInstance]:
        self.last_status = "Not started"
        self.last_error = None
        self.last_stdout = ""
        self.last_stderr = ""
        self.last_call_graph_nodes = []
        self.last_call_graph_edges = []

        with tempfile.TemporaryDirectory(prefix="smell_ai_") as out_dir:
            ok = self._run_smell_ai(root_dir, out_dir)
            if not ok:
                return []
            self._load_call_graph(out_dir)

            csv_path = os.path.join(out_dir, "output", "overview.csv")
            if not os.path.exists(csv_path):
                out_text = f"{self.last_stdout}\n{self.last_stderr}".lower()
                # CodeSmile intentionally skips overview.csv when no smells are found.
                if "no results to save for overview.csv" in out_text:
                    self.last_status = "CodeSmile executed: 0 ML smells found"
                    self.last_error = None
                    return []
                self.last_status = "CodeSmile executed but no overview.csv produced"
                self.last_error = "Missing output/overview.csv"
                return []

            smells: List[SmellInstance] = []
            try:
                with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        file_path = row.get("filename", "")
                        smell_name = row.get("smell_name", "") or "ML Smell"
                        line = self._to_int(row.get("line", ""))
                        description = row.get("description", "") or ""
                        additional = row.get("additional_info", "") or ""
                        message = description if description else f"{smell_name} detected."
                        if additional:
                            message = f"{message} {additional}".strip()

                        if file_author_map:
                            try:
                                rel = os.path.relpath(file_path, root_dir)
                            except Exception:
                                rel = file_path
                            author = file_author_map.get(rel) or file_author_map.get(file_path)
                            entities = [author] if author else [file_path]
                        else:
                            entities = [file_path]

                        smells.append(SmellInstance(
                            smell_id=self._smell_id(smell_name),
                            name=smell_name.replace("_", " ").title(),
                            type="ML",
                            description=message,
                            affected_entities=entities,
                            file_path=file_path or None,
                            line=line,
                            message=message,
                            snippet=None,
                            refactoring_suggestion=additional or None
                        ))
            except Exception:
                self.last_status = "CodeSmile output parsing failed"
                self.last_error = "Failed to parse overview.csv"
                return []

            self.last_status = "CodeSmile executed and parsed"
            return smells
