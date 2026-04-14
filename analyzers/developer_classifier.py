from typing import Dict, List, Optional, Set, Tuple
import os
import re

from models.schemas import Commit, Developer


class DeveloperClassifier:
    """
    Rule-based role classifier.
    Signals used:
    - Libraries/imports detected in touched files.
    - Commit message keyword patterns.
    - PR/Issue text keyword patterns (title/body/comments/reviews).
    """

    AI_EXTENSIONS = {".ipynb", ".h5", ".onnx", ".pickle", ".pkl", ".model", ".pt", ".ckpt"}
    SE_EXTENSIONS = {
        ".java", ".c", ".cpp", ".h", ".js", ".ts", ".css", ".html", ".sql",
        ".go", ".rs", ".yaml", ".yml", ".toml", ".ini", ".conf",
    }

    AI_LIBRARIES = {
        "torch", "tensorflow", "keras", "sklearn", "scikit_learn", "xgboost", "lightgbm", "catboost",
        "opencv_python", "cv2", "transformers", "datasets", "tokenizers",
        "sentence_transformers", "onnx", "onnxruntime", "jax", "flax", "pytorch_lightning", "lightning",
        "fastai", "spacy", "nltk", "gensim", "mlflow", "kubeflow", "tfx", "faiss", "faiss_cpu",
        "stable_baselines3", "ray", "trl", "peft", "diffusers",
    }
    AI_WEAK_LIBRARIES = {
        # Common in many non-ML Python repos: lower weight to reduce AI false positives.
        "numpy", "pandas", "scipy",
    }
    SE_LIBRARIES = {
        "fastapi", "flask", "django", "sqlalchemy", "alembic", "psycopg2", "mysqlclient", "requests",
        "aiohttp", "httpx", "grpc", "protobuf", "celery", "redis", "kafka", "pika", "boto3",
        "uvicorn", "gunicorn", "pytest", "unittest", "loguru", "structlog", "prometheus_client",
        "express", "nestjs", "koa", "typeorm", "mongoose", "spring", "springframework", "hibernate",
        "junit", "log4j", "slf4j", "actix_web", "tokio", "axum",
    }

    AI_PATTERNS = {
        "train", "training", "inference", "embedding", "transformer", "neural", "hyperparameter",
        "classification", "regression", "tokenization", "finetune", "fine_tune", "llm", "model serving",
        "feature engineering", "experiment", "prompt", "checkpoint",
    }
    SE_PATTERNS = {
        "api", "endpoint", "service", "controller", "middleware", "database", "migration", "auth",
        "deploy", "security", "observability", "integration", "refactor", "bugfix", "ci", "cd",
        "slo", "latency", "throughput", "rollback", "incident", "hotfix",
    }

    _TEXT_FILE_MAX_BYTES = 350_000

    def _normalize_pkg(self, name: str) -> str:
        pkg = (name or "").strip().lower().replace("-", "_")
        if pkg.startswith("@"):
            parts = pkg.split("/", 1)
            pkg = parts[-1] if parts else pkg
        return pkg

    def _read_text_file(self, filepath: str) -> str:
        try:
            if not os.path.isfile(filepath):
                return ""
            if os.path.getsize(filepath) > self._TEXT_FILE_MAX_BYTES:
                return ""
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""

    def _extract_dependency_candidates(self, rel_path: str, text: str) -> Set[str]:
        rel_l = (rel_path or "").lower().replace("\\", "/")
        tokens: Set[str] = set()

        if rel_l.endswith((".py", ".pyi")):
            for m in re.findall(r"^\s*(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)", text, flags=re.MULTILINE):
                tokens.add(self._normalize_pkg(m.split(".", 1)[0]))

        if any(rel_l.endswith(x) for x in ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py", "setup.cfg", "environment.yml", "environment.yaml")):
            for m in re.findall(r"([a-zA-Z_][a-zA-Z0-9_\-\.]+)", text):
                tokens.add(self._normalize_pkg(m))

        if rel_l.endswith((".js", ".jsx", ".ts", ".tsx", "package.json")):
            for m in re.findall(r"(?:from\s+['\"]([^'\"]+)['\"]|require\(\s*['\"]([^'\"]+)['\"]\s*\))", text):
                pkg = (m[0] or m[1] or "").strip()
                if pkg:
                    tokens.add(self._normalize_pkg(pkg.split("/", 1)[0]))
            for m in re.findall(r"['\"]([@a-zA-Z0-9_\-\.\/]+)['\"]\s*:\s*['\"][^'\"]+['\"]", text):
                tokens.add(self._normalize_pkg(m))

        if rel_l.endswith((".java", ".kt", ".scala")):
            for m in re.findall(r"^\s*import\s+([a-zA-Z_][a-zA-Z0-9_\.]*)", text, flags=re.MULTILINE):
                tokens.add(self._normalize_pkg(m.split(".", 1)[0]))

        if any(rel_l.endswith(x) for x in ("pom.xml", "build.gradle", "build.gradle.kts", "go.mod")):
            for m in re.findall(r"[a-zA-Z_][a-zA-Z0-9_\-\.\/]*", text):
                tokens.add(self._normalize_pkg(m))

        return {t for t in tokens if t}

    def _dependency_signals(
        self,
        repo_root: Optional[str],
        rel_path: str,
        cache: Dict[str, Tuple[Set[str], Set[str]]],
    ) -> Tuple[Set[str], Set[str]]:
        key = (rel_path or "").replace("\\", "/")
        if key in cache:
            return cache[key]

        ai_hits: Set[str] = set()
        se_hits: Set[str] = set()

        if repo_root and key and not os.path.isabs(key):
            full = os.path.normpath(os.path.join(repo_root, key))
            try:
                if os.path.commonpath([os.path.abspath(repo_root), os.path.abspath(full)]) == os.path.abspath(repo_root):
                    text = self._read_text_file(full)
                    if text:
                        tokens = self._extract_dependency_candidates(key, text)
                        ai_hits = {t for t in tokens if t in self.AI_LIBRARIES}
                        se_hits = {t for t in tokens if t in self.SE_LIBRARIES}
            except Exception:
                pass

        cache[key] = (ai_hits, se_hits)
        return ai_hits, se_hits

    def _count_pattern_hits(self, text: str, patterns: Set[str]) -> int:
        if not text:
            return 0
        t = text.lower()
        hits = 0
        for p in patterns:
            p = (p or "").strip().lower()
            if not p:
                continue
            if " " in p:
                if p in t:
                    hits += 1
            else:
                if re.search(rf"(?<![a-z0-9_]){re.escape(p)}(?![a-z0-9_])", t):
                    hits += 1
        return hits

    def classify_developers(
        self,
        developers: List[Developer],
        commits: List[Commit],
        repo_root: Optional[str] = None,
        gh_text_by_dev: Optional[Dict[str, List[str]]] = None,
    ):
        dev_scores: Dict[str, Dict[str, float]] = {d.id: {"se": 0.0, "ai": 0.0} for d in developers}
        dep_cache: Dict[str, Tuple[Set[str], Set[str]]] = {}

        # Commit/file/library signals.
        for commit in commits:
            author_id = commit.author_id
            if author_id not in dev_scores:
                continue

            msg = (commit.message or "").lower()
            ai_msg_hits = self._count_pattern_hits(msg, self.AI_PATTERNS)
            se_msg_hits = self._count_pattern_hits(msg, self.SE_PATTERNS)
            dev_scores[author_id]["ai"] += ai_msg_hits * 0.35
            dev_scores[author_id]["se"] += se_msg_hits * 0.35

            for file in commit.files_modified or []:
                file_l = str(file).lower()
                _, ext = os.path.splitext(file_l)

                if ext in self.AI_EXTENSIONS:
                    dev_scores[author_id]["ai"] += 1.2
                elif ext in self.SE_EXTENSIONS:
                    dev_scores[author_id]["se"] += 1.0
                elif ext == ".py":
                    # Neutral, low signal.
                    dev_scores[author_id]["ai"] += 0.10
                    dev_scores[author_id]["se"] += 0.10

                ai_deps, se_deps = self._dependency_signals(repo_root, file, dep_cache)
                strong_ai_deps = {x for x in ai_deps if x not in self.AI_WEAK_LIBRARIES}
                weak_ai_deps = {x for x in ai_deps if x in self.AI_WEAK_LIBRARIES}
                dev_scores[author_id]["ai"] += len(strong_ai_deps) * 2.0
                dev_scores[author_id]["ai"] += len(weak_ai_deps) * 0.7
                dev_scores[author_id]["se"] += len(se_deps) * 2.0
                if ai_deps and se_deps:
                    dev_scores[author_id]["ai"] += 0.35
                    dev_scores[author_id]["se"] += 0.35

        # PR/Issue textual signals (title/body/comments/reviews).
        for dev in developers:
            texts = list((gh_text_by_dev or {}).get(dev.id, []) or [])
            if not texts:
                continue
            joined = "\n".join(texts)
            ai_gh_hits = self._count_pattern_hits(joined, self.AI_PATTERNS | self.AI_LIBRARIES)
            se_gh_hits = self._count_pattern_hits(joined, self.SE_PATTERNS | self.SE_LIBRARIES)
            dev_scores[dev.id]["ai"] += ai_gh_hits * 0.30
            dev_scores[dev.id]["se"] += se_gh_hits * 0.30

        # Final label.
        for dev in developers:
            se = float(dev_scores[dev.id]["se"])
            ai = float(dev_scores[dev.id]["ai"])
            total = se + ai

            if total < 1.0:
                dev.classification = "Unknown"
                dev.se_score = 0.0
                dev.ai_score = 0.0
                dev.ml_score = 0.0
                continue

            se_ratio = se / max(total, 1e-9)
            ai_ratio = ai / max(total, 1e-9)
            dev.se_score = round(se_ratio * 10.0, 1)
            dev.ai_score = round(ai_ratio * 10.0, 1)
            dev.ml_score = dev.ai_score

            if total >= 1.6 and abs(se_ratio - ai_ratio) <= 0.16:
                dev.classification = "Hybrid"
            elif se >= 1.4 and ai >= 1.4 and abs(se_ratio - ai_ratio) <= 0.24:
                dev.classification = "Hybrid"
            elif se_ratio >= 0.62 and (se - ai) >= 0.9:
                dev.classification = "Software Engineer"
            elif ai_ratio >= 0.62 and (ai - se) >= 0.9:
                dev.classification = "AI-Engineer"
            elif se >= 1.2 and ai >= 1.2:
                dev.classification = "Hybrid"
            else:
                # Mildly conservative fallback: keep Unknown only for truly weak evidence.
                if se_ratio >= 0.55 and se >= 1.0:
                    dev.classification = "Software Engineer"
                elif ai_ratio >= 0.55 and ai >= 1.0:
                    dev.classification = "AI-Engineer"
                else:
                    dev.classification = "Unknown"
