from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed, Future
import threading
import os
import uuid
import shutil
import csv
import io
import ast
import tempfile
import traceback
import re
from datetime import datetime, timedelta
import subprocess
import networkx as nx
from urllib.parse import quote
from urllib.request import Request, urlopen
from pydantic import BaseModel, Field
import requests
from requests.adapters import HTTPAdapter

_GITHUB_SESSION = requests.Session()
_github_adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100)
_GITHUB_SESSION.mount('https://', _github_adapter)
_GITHUB_SESSION.mount('http://', _github_adapter)


import sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

IS_FROZEN = bool(getattr(sys, "frozen", False))
_BUNDLE_ROOT = getattr(sys, "_MEIPASS", PROJECT_ROOT) if IS_FROZEN else PROJECT_ROOT
RESOURCE_ROOT = os.path.abspath(os.environ.get("SMELLHUB_RESOURCE_ROOT", _BUNDLE_ROOT))
_DEFAULT_DATA_ROOT = os.path.join(os.path.expanduser("~"), ".smellhub") if IS_FROZEN else os.path.join(PROJECT_ROOT, "data")
DATA_ROOT = os.path.abspath(os.environ.get("SMELLHUB_DATA_DIR", _DEFAULT_DATA_ROOT))
PROJECTS_ROOT = os.path.join(DATA_ROOT, "projects")

from models.schemas import (
    Project,
    ProjectMetrics,
    ProjectTimeWindow,
    SmellInstance,
    Developer,
    Commit,
    VulnerabilityInstance,
    TopicModelingResult,
    RoleTopicTree,
    DeveloperTopicProfile,
    DeveloperConflictRecord,
    PotentialConflictThread,
    TopicNode,
    TopicSubtopic,
    TraceabilityLink,
    LLMSettingsResponse,
    LLMSettingsUpdateRequest,
)
from core.miner import RepositoryMiner
from core.network_builder import NetworkBuilder
from analyzers.community_smells import CommunitySmellAnalyzer
from analyzers.developer_classifier import DeveloperClassifier
from analyzers.quality_metrics import QualityMetricsAnalyzer
from analyzers.ml_smells import MLSmellAnalyzer
from analyzers.traditional_smells import TraditionalSmellAnalyzer
from analyzers.rszz import RSZZAnalyzer
from analyzers.vulnerabilities import BanditVulnerabilityAnalyzer
from analyzers.developer_sentiment import DeveloperSentimentAnalyzer
from analyzers.role_topic_modeling import RoleTopicModelingAnalyzer

app = FastAPI(title="Community Smells Hub API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

import json

PROJECTS_FILE = os.path.join(DATA_ROOT, "projects.json")
TOPIC_DOCS_ROOT = os.path.join(DATA_ROOT, "topic_documents")
LLM_SETTINGS_FILE = os.path.join(DATA_ROOT, "llm_settings.json")
os.makedirs(os.path.dirname(PROJECTS_FILE), exist_ok=True)
GITHUB_CACHE_DIR = os.path.join(DATA_ROOT, "github_cache")
os.makedirs(PROJECTS_ROOT, exist_ok=True)
os.makedirs(TOPIC_DOCS_ROOT, exist_ok=True)
os.makedirs(GITHUB_CACHE_DIR, exist_ok=True)

import hashlib
def _get_url_cache_path(url: str) -> str:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return os.path.join(GITHUB_CACHE_DIR, f"{h}.json")

def _load_persistent_cache(url: str) -> Optional[Any]:
    path = _get_url_cache_path(url)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def _save_persistent_cache(url: str, data: Any) -> None:
    if data is None:
        return
    path = _get_url_cache_path(url)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass
_PROJECTS_IO_LOCK = threading.RLock()
_PROJECTS_DB_LOCK = threading.RLock()
_TOPIC_DOCS_LOCK = threading.RLock()
_LLM_SETTINGS_LOCK = threading.RLock()
_GLOBAL_TOPICS_CACHE = TopicModelingResult()
_GLOBAL_TOPICS_LOCK = threading.RLock()

_PRONOUN_FILE_CANDIDATES = [
    os.environ.get("PRONOUN_PARADIGMS_FILE", "").strip(),
    os.path.join(RESOURCE_ROOT, "pronoun_paradigms_coling2022.txt"),
    os.path.join(PROJECT_ROOT, "pronoun_paradigms_coling2022.txt"),
    os.path.join(os.path.dirname(PROJECT_ROOT), "community_smells", "pronoun_paradigms_coling2022.txt"),
]
_NO_PRONOUN_PHRASES = {
    "no pronouns",
    "use my name",
    "name only",
    "without pronouns",
}
_DEFAULT_PRONOUN_SETS: Dict[str, set] = {
    "masculine": {"he", "him", "his", "himself"},
    "feminine": {"she", "her", "hers", "herself"},
    "neutral": {"they", "them", "their", "theirs", "themself"},
    "neopronouns": {"thon", "thons", "thonself", "xe", "xem", "xyr", "xyrs", "xemself", "ze", "zir", "zirs", "zirself", "e", "em", "es", "ems", "emself", "ey", "eir", "eirs"},
    "nounself": {"star", "stars", "starself", "vam", "vamp", "vamps", "vampself", "kitten", "kittens", "kittenself"},
    "numberself": {"0", "0s", "0self", "1", "1s", "1self"},
    "nameself": {"john", "johns", "johnself"},
}
_PRONOUN_SETS_CACHE: Optional[Dict[str, set]] = None


def _analyze_snapshot_worker(args: Tuple[str, str, str, str, bool, Dict[str, str], Dict[str, Developer]]) -> Dict[str, Any]:
    (
        snapshot_hash,
        source_repo_path,
        dpy_binary,
        smell_ai_root,
        vulnerabilities_enabled,
        email_to_dev_id,
        known_dev_ids
    ) = args

    import tempfile
    import tarfile
    import io
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime
    from typing import List, Dict, Any, Tuple, Optional
    from analyzers.ml_smells import MLSmellAnalyzer
    from analyzers.traditional_smells import TraditionalSmellAnalyzer
    from analyzers.vulnerabilities import BanditVulnerabilityAnalyzer

    ml_analyzer = MLSmellAnalyzer(smell_ai_root=smell_ai_root)
    traditional_analyzer = TraditionalSmellAnalyzer(dpy_binary=dpy_binary)
    vuln_analyzer = BanditVulnerabilityAnalyzer() if vulnerabilities_enabled else None

    # We use a temporary directory to avoid collisions between parallel workers
    with tempfile.TemporaryDirectory(prefix=f"snap_{snapshot_hash[:8]}_") as temp_root:
        # Extract snapshot to temp_root using git archive (fast and no .git folder needed)
        try:
            archive_cmd = ["git", "-C", source_repo_path, "archive", "--format=tar", snapshot_hash]
            proc = subprocess.run(archive_cmd, capture_output=True, check=True)
            with io.BytesIO(proc.stdout) as bio:
                with tarfile.open(fileobj=bio) as tf:
                    tf.extractall(path=temp_root)
        except Exception as e:
            return {
                "snapshot_hash": snapshot_hash,
                "error": f"Failed to extract snapshot {snapshot_hash}: {str(e)}",
            }

        # Run Heavy Analyzers using a ThreadPool inside the process worker
        snapshot_workers = 3 if vulnerabilities_enabled else 2
        with ThreadPoolExecutor(max_workers=snapshot_workers) as snapshot_pool:
            fut_ml = snapshot_pool.submit(ml_analyzer.analyze_directory, temp_root, None)
            fut_trad = snapshot_pool.submit(
                traditional_analyzer.analyze_directory,
                temp_root,
                email_to_dev_id,
            )
            fut_vuln = snapshot_pool.submit(
                vuln_analyzer.analyze_directory,
                temp_root,
                email_to_dev_id,
            ) if vuln_analyzer else None

            try:
                snap_ml = fut_ml.result()
            except Exception as e:
                snap_ml = []

            try:
                snap_traditional = fut_trad.result()
            except Exception as e:
                snap_traditional = []

            if fut_vuln is not None:
                try:
                    snap_vulnerabilities = fut_vuln.result()
                except Exception:
                    snap_vulnerabilities = []
            else:
                snap_vulnerabilities = []

        # We must attribute in the worker using the original repo for blaming, but the relative paths from the snapshot
        ml_enriched = _attribute_instances_to_developers_parallel_worker(
            snap_ml, source_repo_path, snapshot_hash, email_to_dev_id, known_dev_ids
        )
        traditional_enriched = _attribute_instances_to_developers_parallel_worker(
            snap_traditional, source_repo_path, snapshot_hash, email_to_dev_id, known_dev_ids
        )
        vulnerabilities_enriched = _attribute_instances_to_developers_parallel_worker(
            snap_vulnerabilities, source_repo_path, snapshot_hash, email_to_dev_id, known_dev_ids
        )

        loc_est, nom_est = _compute_loc_nom_for_snapshot(temp_root)

        return {
            "snapshot_hash": snapshot_hash,
            "ml_enriched": ml_enriched,
            "traditional_enriched": traditional_enriched,
            "vulnerabilities_enriched": vulnerabilities_enriched,
            "loc": loc_est,
            "nom": nom_est,
            "ml_status": ml_analyzer.last_status,
            "ml_error": ml_analyzer.last_error,
            "ml_stdout": (ml_analyzer.last_stdout or "")[:4000] or None,
            "ml_stderr": (ml_analyzer.last_stderr or "")[:4000] or None,
            "ml_call_graph_nodes": ml_analyzer.last_call_graph_nodes,
            "ml_call_graph_edges": ml_analyzer.last_call_graph_edges,
        }

def _attribute_instances_to_developers_parallel_worker(
    instances: List[Any],
    repo_path: str,
    ref: str,
    email_to_dev_id: Dict[str, str],
    known_dev_ids: Dict[str, Developer],
) -> List[Tuple[Any, Optional[datetime]]]:
    valid_ids = set(known_dev_ids.keys())
    enriched: List[Tuple[Any, Optional[datetime]]] = []

    for inst in instances:
        entities = [x for x in getattr(inst, "affected_entities", []) if isinstance(x, str)]
        file_path = getattr(inst, "file_path", None)
        line = getattr(inst, "line", None)
        line_no = int(line) if line else None
        intro_date: Optional[datetime] = None

        info = None
        if file_path and line_no:
            # We use ref in the blame call to ensure we blame the correct version (snapshot)
            info = _blame_line_info_at_ref(repo_path, ref, file_path, line_no)
            if info and isinstance(info, dict):
                intro_date = info.get("author_date")

        if not any(e in valid_ids for e in entities):
            email = info.get("author_email") if isinstance(info, dict) else None
            author_id = email_to_dev_id.get(str(email).lower()) if email else None
            if author_id:
                inst.affected_entities = [author_id]
        
        enriched.append((inst, intro_date))
    return enriched

def _blame_line_info_at_ref(repo_path: str, ref: str, file_path: Optional[str], line: Optional[int]) -> Optional[Dict[str, object]]:
    if not file_path or not line:
        return None
    
    # We ensure we have a relative path for git blame
    rel = file_path
    if os.path.isabs(file_path):
        try:
            rel = os.path.relpath(file_path, repo_path)
        except Exception:
            pass

    # Note the 'ref' argument before '--' to blame the specific commit snapshot
    cmd = ["git", "-C", repo_path, "blame", "--line-porcelain", "-L", f"{line},{line}", ref, "--", rel]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        stdout = res.stdout or ""
        commit_hash = ""
        author_email = ""
        author_time = None
        
        for row in stdout.splitlines():
            # Match 40-char SHA1 at start of porcelain output
            m = re.match(r"^([0-9a-f]{40})", row)
            if m:
                commit_hash = m.group(1)
            elif row.startswith("author-mail "):
                author_email = row.split(" ", 1)[1].strip("<>")
            elif row.startswith("author-time "):
                # author-time is a unix timestamp
                author_time = datetime.fromtimestamp(int(row.split(" ", 1)[1]))
                break
        
        return {
            "commit_hash": commit_hash or None,
            "author_email": author_email or None,
            "author_date": author_time,
        }
    except Exception:
        return None


def load_projects() -> Dict[str, Project]:
    if os.path.exists(PROJECTS_FILE):
        try:
            with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {k: Project(**v) for k, v in data.items()}
        except Exception as e:
            print(f"Error loading projects: {e}")
    return {}


def save_projects(db: Dict[str, Project]):
    try:
        with _PROJECTS_IO_LOCK:
            with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
                data = {k: v.model_dump(mode='json') for k, v in db.items()}
                json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving projects: {e}")


def _mask_api_key(value: str) -> str:
    raw = str(value or "").strip()
    if len(raw) <= 8:
        return "*" * len(raw)
    return f"{raw[:4]}...{raw[-4:]}"


def _load_llm_settings_raw() -> Dict[str, Any]:
    if not os.path.exists(LLM_SETTINGS_FILE):
        return {}
    try:
        with _LLM_SETTINGS_LOCK:
            with open(LLM_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_llm_settings_raw(data: Dict[str, Any]) -> None:
    payload = dict(data or {})
    with _LLM_SETTINGS_LOCK:
        with open(LLM_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=True)


def _effective_llm_config() -> Dict[str, Any]:
    stored = _load_llm_settings_raw()
    llm_runs_raw = stored.get("llm_runs")
    try:
        llm_runs = int(llm_runs_raw if llm_runs_raw is not None else os.environ.get("SMELLHUB_TOPIC_RUNS", "1"))
    except Exception:
        llm_runs = 1
    llm_runs = max(1, min(7, llm_runs))
    return {
        "api_key": str(stored.get("api_key") or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip() or os.environ.get("SMELLHUB_OPENAI_API_KEY", "").strip(),
        "model": str(stored.get("model") or "").strip() or os.environ.get("SMELLHUB_TOPIC_MODEL", "gpt-5-mini").strip(),
        "llm_runs": llm_runs,
        "organization": str(stored.get("organization") or "").strip() or os.environ.get("OPENAI_ORGANIZATION", "").strip(),
        "project": str(stored.get("project") or "").strip() or os.environ.get("OPENAI_PROJECT", "").strip(),
        "endpoint": str(stored.get("endpoint") or "").strip() or os.environ.get("SMELLHUB_OPENAI_CHAT_ENDPOINT", "https://api.openai.com/v1/chat/completions").strip(),
    }


def _effective_github_token() -> str:
    stored = _load_llm_settings_raw()
    return (
        str(stored.get("github_token") or "").strip()
        or os.environ.get("GITHUB_TOKEN", "").strip()
    )


def _read_int_env(name: str, default: int, min_value: int = 0) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return int(default)
    try:
        return max(int(min_value), int(raw))
    except Exception:
        return int(default)


def _github_get_json(
    url: str,
    token: str,
    timeout_sec: int,
    cache: Optional[Dict[str, Any]] = None,
    use_persistent_cache: bool = True,
) -> Optional[Any]:
    if cache is not None and url in cache:
        return cache[url]

    if use_persistent_cache:
        persistent = _load_persistent_cache(url)
        if persistent is not None:
            if cache is not None:
                cache[url] = persistent
            return persistent

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "community-smells-hub",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    try:
        res = _GITHUB_SESSION.get(url, headers=headers, timeout=timeout_sec)
        if res.status_code == 200:
            payload = res.json()
        else:
            payload = None
    except Exception:
        payload = None

    if use_persistent_cache and payload is not None:
        _save_persistent_cache(url, payload)

    if cache is not None:
        cache[url] = payload
    return payload


def _build_llm_settings_response() -> LLMSettingsResponse:
    config = _effective_llm_config()
    api_key = str(config.get("api_key") or "").strip()
    github_token = _effective_github_token()
    return LLMSettingsResponse(
        provider="OpenAI",
        model=str(config.get("model") or "gpt-5-mini"),
        llm_runs=max(1, int(config.get("llm_runs") or 1)),
        organization=str(config.get("organization") or ""),
        project=str(config.get("project") or ""),
        endpoint=str(config.get("endpoint") or "https://api.openai.com/v1/chat/completions"),
        has_api_key=bool(api_key),
        api_key_masked=_mask_api_key(api_key) if api_key else "",
        has_github_token=bool(github_token),
        github_token_masked=_mask_api_key(github_token) if github_token else "",
    )


def _topic_docs_path(project_id: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(project_id or "").strip()) or "project"
    return os.path.join(TOPIC_DOCS_ROOT, f"{safe_id}.json")


def _save_topic_documents(project_id: str, documents: List[Dict[str, Any]]) -> None:
    path = _topic_docs_path(project_id)
    payload = list(documents or [])
    with _TOPIC_DOCS_LOCK:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=True)


def _load_topic_documents(project_id: str) -> List[Dict[str, Any]]:
    path = _topic_docs_path(project_id)
    if not os.path.exists(path):
        return []
    try:
        with _TOPIC_DOCS_LOCK:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _delete_topic_documents(project_id: str) -> None:
    path = _topic_docs_path(project_id)
    if not os.path.exists(path):
        return
    try:
        with _TOPIC_DOCS_LOCK:
            os.remove(path)
    except Exception:
        pass


def _invalidate_global_topics_cache() -> None:
    global _GLOBAL_TOPICS_CACHE
    with _GLOBAL_TOPICS_LOCK:
        _GLOBAL_TOPICS_CACHE = TopicModelingResult()


def _collect_llm_only_documents(project: Project) -> List[Dict[str, Any]]:
    _ensure_project_repo_available(project)
    miner = RepositoryMiner(project.local_path)
    commits = sorted(miner.list_commits(), key=lambda c: c.date)
    now = datetime.now()
    if commits:
        project_start = commits[0].date
        # For standalone LLM analysis we want the full current discussion history,
        # not only threads updated before the last commit in the local clone.
        project_end = now + timedelta(seconds=1)
    else:
        project_start = now - timedelta(days=365)
        project_end = now + timedelta(seconds=1)

    all_developers = miner.get_developers()
    github_http_cache: Dict[str, Any] = {}
    login_to_dev_id = _build_login_to_dev_id_map(all_developers)
    login_to_dev_id = _augment_login_to_dev_id_map_with_github_contributors(
        project.url,
        all_developers,
        login_to_dev_id,
        http_cache=github_http_cache,
    )
    _, gh_text_signals_all = _fetch_github_issue_pr_data(
        project.url,
        project_start,
        project_end,
        login_to_dev_id,
        http_cache=github_http_cache,
    )
    gh_text_by_dev: Dict[str, List[str]] = {}
    for signal in gh_text_signals_all:
        if not isinstance(signal, dict):
            continue
        dev_id = str(signal.get("developer_id") or "").strip()
        txt = str(signal.get("text") or "").strip()
        if dev_id and txt:
            gh_text_by_dev.setdefault(dev_id, []).append(txt)

    classifier = DeveloperClassifier()
    classifier.classify_developers(
        all_developers,
        commits,
        repo_root=project.local_path,
        gh_text_by_dev=gh_text_by_dev,
    )
    dev_by_id = {dev.id: dev for dev in all_developers if dev.id}
    repo_web_base = _github_repo_web_base(project.url)
    window_meta = {
        "id": "all_history",
        "label": "All History",
    }

    documents: List[Dict[str, Any]] = []
    for commit in commits:
        if not commit.author_id or not commit.message:
            continue
        dev = dev_by_id.get(commit.author_id)
        role = dev.classification if dev else "Unknown"
        doc = _build_interaction_document(
            project=project,
            window_meta=window_meta,
            source_type="commit_message",
            developer_id=commit.author_id,
            role=role,
            text=commit.message,
            timestamp=commit.date,
            source_id=f"commit:{commit.hash}",
            source_label=f"Commit {str(commit.hash or '')[:7]}",
            source_url=f"{repo_web_base}/commit/{commit.hash}" if repo_web_base and commit.hash else "",
            is_open=False,
            thread_id=f"commit:{commit.hash}",
            thread_label=f"Commit {str(commit.hash or '')[:7]}",
            thread_url=f"{repo_web_base}/commit/{commit.hash}" if repo_web_base and commit.hash else "",
            thread_is_open=False,
        )
        if doc:
            documents.append(doc)

    for signal in gh_text_signals_all:
        if not isinstance(signal, dict):
            continue
        dev_id = str(signal.get("developer_id") or "").strip()
        if not dev_id:
            continue
        dev = dev_by_id.get(dev_id)
        role = dev.classification if dev else "Unknown"
        doc = _build_interaction_document(
            project=project,
            window_meta=window_meta,
            source_type=str(signal.get("source_type") or "issue_pr"),
            developer_id=dev_id,
            role=role,
            text=str(signal.get("text") or ""),
            timestamp=signal.get("timestamp"),
            source_id=str(signal.get("source_id") or ""),
            source_label=str(signal.get("source_label") or ""),
            source_url=str(signal.get("source_url") or ""),
            is_open=bool(signal.get("is_open")),
            thread_id=str(signal.get("thread_id") or ""),
            thread_label=str(signal.get("thread_label") or ""),
            thread_url=str(signal.get("thread_url") or ""),
            thread_is_open=bool(signal.get("thread_is_open")),
        )
        if doc:
            documents.append(doc)

    _save_topic_documents(project.id, documents)
    return documents


def _build_interaction_document(
    project: Project,
    window_meta: Dict[str, Any],
    source_type: str,
    developer_id: str,
    role: str,
    text: str,
    timestamp: Optional[datetime],
    source_id: str = "",
    source_label: str = "",
    source_url: str = "",
    is_open: bool = False,
    thread_id: str = "",
    thread_label: str = "",
    thread_url: str = "",
    thread_is_open: bool = False,
) -> Optional[Dict[str, Any]]:
    content = re.sub(r"\s+", " ", str(text or "")).strip()
    if not content:
        return None
    source_kind = str(source_type or "").strip() or "unknown"
    final_source_id = str(source_id or "").strip()
    if not final_source_id:
        timestamp_label = timestamp.isoformat() if isinstance(timestamp, datetime) else "na"
        final_source_id = f"{source_kind}:{developer_id}:{window_meta.get('id') or 'window'}:{timestamp_label}"
    final_source_label = str(source_label or "").strip() or final_source_id
    final_thread_id = str(thread_id or "").strip() or final_source_id
    final_thread_label = str(thread_label or "").strip() or final_source_label
    return {
        "project_id": project.id,
        "project_name": project.name,
        "time_window_id": str(window_meta.get("id") or ""),
        "time_window_label": str(window_meta.get("label") or ""),
        "source_id": final_source_id,
        "source_label": final_source_label,
        "source_url": str(source_url or "").strip(),
        "source_type": source_kind,
        "is_open": bool(is_open),
        "thread_id": final_thread_id,
        "thread_label": final_thread_label,
        "thread_url": str(thread_url or source_url or "").strip(),
        "thread_is_open": bool(thread_is_open),
        "developer_id": str(developer_id or "").strip(),
        "role": str(role or "Unknown"),
        "text": content[:500],
        "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else "",
    }


projects_db: Dict[str, Project] = load_projects()

_stale_running_fixed = False
_legacy_progress_fixed = False
_STARTUP_RESUME_PROJECT_IDS: List[str] = []
for _p in projects_db.values():
    if _p.analysis_status in {"Running", "Queued", "Queued for automatic resume"}:
        _p.analysis_status = "Queued for automatic resume"
        _p.analysis_eta_seconds = None
        _p.ml_detection_status = "Interrupted by server restart; automatic resume queued."
        _STARTUP_RESUME_PROJECT_IDS.append(_p.id)
        _stale_running_fixed = True
    elif _p.analysis_status == "Completed":
        if float(_p.analysis_progress_pct or 0.0) <= 0.0:
            _p.analysis_progress_pct = 100.0
            _legacy_progress_fixed = True
        if _p.analysis_eta_seconds is None:
            _p.analysis_eta_seconds = 0
            _legacy_progress_fixed = True
if _stale_running_fixed or _legacy_progress_fixed:
    save_projects(projects_db)


def _machine_cpu_count() -> int:
    try:
        return max(1, int(os.cpu_count() or 1))
    except Exception:
        return 1


def _adaptive_analysis_parallelism() -> int:
    # Full analysis is heavy (mining + smell analysis + model work), so we keep
    # a conservative default based on CPU cores and leave one core free.
    cpu = _machine_cpu_count()
    return max(1, min(8, max(1, cpu - 1)))


def _adaptive_import_parallelism() -> int:
    # Import/clone is mostly I/O bound, so we can be a bit more aggressive.
    cpu = _machine_cpu_count()
    return max(2, min(24, cpu * 2))


def _adaptive_github_parallelism() -> int:
    cpu = _machine_cpu_count()
    return max(8, min(64, cpu * 4))


def _read_parallelism_env(name: str, default_value: int) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return int(default_value)
    try:
        return max(1, int(raw))
    except Exception:
        return int(default_value)


def _read_bool_env(name: str, default_value: bool) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return bool(default_value)
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default_value)


def _is_vulnerability_analysis_enabled(project: Optional[Project] = None) -> bool:
    if project is not None:
        return bool(getattr(project, "vulnerability_analysis_enabled", False))
    return _read_bool_env("ANALYSIS_ENABLE_VULNERABILITIES", True)


_ANALYSIS_MAX_WORKERS = _read_parallelism_env("ANALYSIS_PARALLELISM", _adaptive_analysis_parallelism())
_ANALYSIS_EXECUTOR = ThreadPoolExecutor(max_workers=_ANALYSIS_MAX_WORKERS)
_RUNNING_ANALYSES: set = set()
_RUNNING_ANALYSES_LOCK = threading.Lock()
_ANALYSIS_FUTURES: Dict[str, Future] = {}
_WORKFLOW_GENERATION = 0
_WORKFLOW_GENERATION_LOCK = threading.Lock()


class AnalysisCancelled(Exception):
    pass


def _get_workflow_generation() -> int:
    with _WORKFLOW_GENERATION_LOCK:
        return int(_WORKFLOW_GENERATION)


def _bump_workflow_generation() -> int:
    global _WORKFLOW_GENERATION
    with _WORKFLOW_GENERATION_LOCK:
        _WORKFLOW_GENERATION += 1
        return int(_WORKFLOW_GENERATION)


def _is_generation_cancelled(expected_generation: Optional[int]) -> bool:
    if expected_generation is None:
        return False
    return int(expected_generation) != _get_workflow_generation()


def _analysis_worker(project_id: str, generation: int) -> None:
    try:
        project = projects_db.get(project_id)
        if project:
            project.analysis_status = "Running"
            if float(project.analysis_progress_pct or 0.0) <= 0.0:
                _set_analysis_progress(project, 0.0, None, 0, 0)
            if not str(project.ml_detection_status or "").strip() or "queued" in str(project.ml_detection_status or "").lower():
                project.ml_detection_status = "Running analysis workers..."
            save_projects(projects_db)
        run_full_analysis(project_id, expected_generation=generation)
    finally:
        with _RUNNING_ANALYSES_LOCK:
            _RUNNING_ANALYSES.discard(project_id)
            _ANALYSIS_FUTURES.pop(project_id, None)


def _enqueue_analysis(project_id: str, generation: Optional[int] = None) -> bool:
    gen = _get_workflow_generation() if generation is None else int(generation)
    if _is_generation_cancelled(gen):
        return False
    with _RUNNING_ANALYSES_LOCK:
        if project_id in _RUNNING_ANALYSES:
            return False
        _RUNNING_ANALYSES.add(project_id)
        fut = _ANALYSIS_EXECUTOR.submit(_analysis_worker, project_id, gen)
        _ANALYSIS_FUTURES[project_id] = fut
    return True


def _resume_queued_analyses_after_restart() -> None:
    if not _STARTUP_RESUME_PROJECT_IDS:
        return
    generation = _get_workflow_generation()
    touched = False
    for project_id in list(dict.fromkeys(_STARTUP_RESUME_PROJECT_IDS)):
        project = projects_db.get(project_id)
        if not project:
            continue
        project.analysis_status = "Queued for automatic resume"
        if not str(project.ml_detection_status or "").strip():
            project.ml_detection_status = "Resuming after backend restart..."
        project.analysis_eta_seconds = None
        queued = _enqueue_analysis(project_id, generation=generation)
        touched = touched or queued
    if touched:
        save_projects(projects_db)


_resume_queued_analyses_after_restart()


def _start_of_month(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_months(dt: datetime, months: int) -> datetime:
    month_idx = (dt.month - 1) + months
    year = dt.year + (month_idx // 12)
    month = (month_idx % 12) + 1
    return dt.replace(year=year, month=month, day=1)


def _window_id(start: datetime, end_exclusive: datetime) -> str:
    end_inclusive = end_exclusive - timedelta(days=1)
    return f"{start.strftime('%Y%m%d')}_{end_inclusive.strftime('%Y%m%d')}"


def _window_label(start: datetime, end_exclusive: datetime) -> str:
    end_inclusive = end_exclusive - timedelta(days=1)
    return f"{start.strftime('%Y-%m-%d')} -> {end_inclusive.strftime('%Y-%m-%d')}"


def _load_pronoun_sets() -> Dict[str, set]:
    global _PRONOUN_SETS_CACHE
    if _PRONOUN_SETS_CACHE is not None:
        return _PRONOUN_SETS_CACHE

    pronouns = {k: set(v) for k, v in _DEFAULT_PRONOUN_SETS.items()}
    file_path = next((p for p in _PRONOUN_FILE_CANDIDATES if p and os.path.exists(p)), None)
    if not file_path:
        _PRONOUN_SETS_CACHE = pronouns
        return pronouns

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read() or ""
    except Exception:
        _PRONOUN_SETS_CACHE = pronouns
        return pronouns

    section = ""
    for raw in text.splitlines():
        line = raw.strip().lower()
        key = re.sub(r"[^a-z0-9]+", " ", line).strip()
        if not line:
            continue

        if "masculine pronoun set" in key:
            section = "masculine"
            continue
        if "feminine pronoun set" in key:
            section = "feminine"
            continue
        if "gender neutral pronouns" in key:
            section = "neutral"
            continue
        if "neopronouns" in key:
            section = "neopronouns"
            continue
        if "nounself pronouns" in key:
            section = "nounself"
            continue
        if "numberself pronouns" in key:
            section = "numberself"
            continue
        if "nameself pronouns" in key:
            section = "nameself"
            continue
        if "alternating pronoun sets" in key or "no pronoun preference" in key:
            section = ""
            continue

        if section not in pronouns:
            continue

        if ":" in line:
            payload = line.split(":", 1)[1]
            tokens = [t for t in re.split(r"[^a-z0-9]+", payload) if t]
            for token in tokens:
                if len(token) <= 20:
                    pronouns[section].add(token)

        if "/" in line:
            tokens = [t for t in re.split(r"[^a-z0-9]+", line) if t]
            if len(tokens) >= 2:
                for token in tokens:
                    if len(token) <= 20:
                        pronouns[section].add(token)

    _PRONOUN_SETS_CACHE = pronouns
    return pronouns


def _build_time_windows(commits: List[Commit], months_per_window: int = 1) -> List[Dict[str, object]]:
    months_per_window = max(1, int(months_per_window or 1))
    if not commits:
        now = datetime.now()
        s = _start_of_month(now)
        e = _add_months(s, months_per_window)
        return [{
            "id": _window_id(s, e),
            "label": _window_label(s, e),
            "start": s,
            "end_exclusive": e,
            "end_inclusive": e - timedelta(seconds=1),
        }]

    min_date = min(c.date for c in commits)
    max_date = max(c.date for c in commits)
    cursor = _start_of_month(min_date)

    windows = []
    while cursor <= max_date:
        nxt = _add_months(cursor, months_per_window)
        windows.append({
            "id": _window_id(cursor, nxt),
            "label": _window_label(cursor, nxt),
            "start": cursor,
            "end_exclusive": nxt,
            "end_inclusive": nxt - timedelta(seconds=1),
        })
        cursor = nxt

    return windows


_BLAME_FILE_CACHE = {}
_BLAME_CACHE_LOCK = threading.Lock()

def _blame_line_info(repo_path: str, file_path: Optional[str], line: Optional[int]) -> Optional[Dict[str, object]]:
    if not file_path or not line:
        return None

    if os.path.isabs(file_path):
        file_abs = file_path
    else:
        file_abs = os.path.join(repo_path, file_path)

    if not os.path.exists(file_abs):
        return None

    with _BLAME_CACHE_LOCK:
        if file_abs not in _BLAME_FILE_CACHE:
            _BLAME_FILE_CACHE[file_abs] = {}
        file_cache = _BLAME_FILE_CACHE[file_abs]

    if file_cache:
        return file_cache.get(line)

    rel = os.path.relpath(file_abs, repo_path)
    cmd = [
        "git", "-C", repo_path, "blame", "--line-porcelain", rel,
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
    current_line = None
    commit_hash = ""
    author_email = ""
    author_time = None
    
    parsed_lines = {}

    for row in stdout.splitlines():
        if row.startswith('\t'):
            if current_line is not None:
                parsed_lines[current_line] = {
                    "commit_hash": commit_hash or None,
                    "author_email": author_email or None,
                    "author_date": author_time,
                }
            current_line = None
            commit_hash = ""
            author_email = ""
            author_time = None
            continue

        parts = row.split()
        if len(parts) >= 3 and len(parts[0]) == 40 and all(c in "0123456789abcdef" for c in parts[0]):
            try:
                current_line = int(parts[2])
                commit_hash = parts[0]
            except ValueError:
                pass
            continue

        if current_line is not None:
            if row.startswith("author-mail "):
                author_email = row.split(" ", 1)[1].strip().strip("<>").lower()
            elif row.startswith("author-time "):
                raw = row.split(" ", 1)[1].strip()
                try:
                    author_time = datetime.fromtimestamp(int(raw))
                except Exception:
                    author_time = None

    with _BLAME_CACHE_LOCK:
        _BLAME_FILE_CACHE[file_abs] = parsed_lines

    return parsed_lines.get(line)


def _clone_developer_identity(dev: Developer) -> Developer:
    return Developer(
        id=dev.id,
        aliases=list(dev.aliases or []),
        emails=list(dev.emails or []),
        gender=dev.gender or "Unknown",
        gender_confidence=float(dev.gender_confidence or 0.0),
        gender_source=dev.gender_source or "none",
        pronouns_detected=list(dev.pronouns_detected or []),
        sentiment_score=float(dev.sentiment_score or 0.0),
        sentiment_label=dev.sentiment_label or "Unknown",
        sentiment_messages_count=int(dev.sentiment_messages_count or 0),
        sentiment_emotions=dict(dev.sentiment_emotions or {}),
        abandoned_since_date=dev.abandoned_since_date,
        last_commit_hash=dev.last_commit_hash,
        last_commit_date=dev.last_commit_date,
        last_commit_message=dev.last_commit_message,
        last_message_before_abandonment_hash=dev.last_message_before_abandonment_hash,
        last_message_before_abandonment_date=dev.last_message_before_abandonment_date,
        last_message_before_abandonment=dev.last_message_before_abandonment,
    )


def _clone_developer_for_export(dev: Developer, *, zero_window_metrics: bool = False) -> Developer:
    if hasattr(dev, "model_dump"):
        payload = dev.model_dump(mode="python")
    elif hasattr(dev, "dict"):
        payload = dev.dict()
    else:
        payload = dict(dev)
    cloned = Developer(**payload)
    if zero_window_metrics:
        cloned.community_smells = []
        cloned.ml_smells = []
        cloned.ml_smell_details = []
        cloned.traditional_smells = []
        cloned.traditional_smell_details = []
        cloned.vulnerabilities = []
        cloned.vulnerability_details = []
        cloned.bug_introduced_count = 0
        cloned.commits_count = 0
        cloned.bug_fix_commits_count = 0
        cloned.files_touched_count = 0
        cloned.lines_added = 0
        cloned.lines_deleted = 0
        cloned.code_churn = 0
        cloned.avg_files_per_commit = 0.0
        cloned.sentiment_score = 0.0
        cloned.sentiment_label = "Unknown"
        cloned.sentiment_messages_count = 0
        cloned.sentiment_emotions = {}
    return cloned


def _window_export_developers(project: Project, window_idx: Optional[int], active_developers: List[Developer]) -> List[Developer]:
    if window_idx is None or not (project.time_windows or []):
        return list(active_developers or [])

    time_windows = list(project.time_windows or [])
    active_map = {dev.id: dev for dev in (active_developers or []) if getattr(dev, "id", None)}
    history_by_dev: Dict[str, List[Tuple[int, Developer]]] = {}
    for idx, tw in enumerate(time_windows[: window_idx + 1]):
        for dev in (tw.developers or []):
            if not dev.id:
                continue
            history_by_dev.setdefault(dev.id, []).append((idx, dev))

    export_devs: List[Developer] = [dev for dev in (active_developers or [])]
    for dev_id, history in history_by_dev.items():
        if dev_id in active_map:
            continue
        last_idx, last_dev = history[-1]
        cloned = _clone_developer_for_export(last_dev, zero_window_metrics=True)
        cloned.last_interaction_window_id = time_windows[last_idx].id
        cloned.last_interaction_window_label = time_windows[last_idx].label
        cloned.is_abandoned = bool(last_idx < window_idx)
        cloned.abandonment_status = "Abandoned" if cloned.is_abandoned else "Active"
        if cloned.is_abandoned:
            abandon_idx = min(last_idx + 1, window_idx)
            cloned.abandoned_since_window_id = time_windows[abandon_idx].id
            cloned.abandoned_since_window_label = time_windows[abandon_idx].label
            cloned.abandoned_since_date = time_windows[abandon_idx].start_date
            cloned.last_message_before_abandonment_hash = cloned.last_commit_hash
            cloned.last_message_before_abandonment_date = cloned.last_commit_date
            cloned.last_message_before_abandonment = cloned.last_commit_message
        else:
            cloned.abandoned_since_window_id = None
            cloned.abandoned_since_window_label = None
            cloned.abandoned_since_date = None
            cloned.last_message_before_abandonment_hash = None
            cloned.last_message_before_abandonment_date = None
            cloned.last_message_before_abandonment = None
        export_devs.append(cloned)

    export_devs.sort(key=lambda d: (not bool(getattr(d, "is_abandoned", False)), -(getattr(d, "commits_count", 0) or 0), d.id))
    return export_devs


def _normalize_identity_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _parse_github_owner_repo(url: str) -> Tuple[Optional[str], Optional[str]]:
    if not url:
        return None, None
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", url.strip(), flags=re.IGNORECASE)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?$", url.strip(), flags=re.IGNORECASE)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _github_repo_web_base(url: str) -> str:
    owner, repo = _parse_github_owner_repo(url)
    if not owner or not repo:
        return ""
    return f"https://github.com/{owner}/{repo}"


def _extract_login_from_noreply(email: str) -> Optional[str]:
    if not email:
        return None
    e = email.strip().lower()
    m = re.match(r"^(?:\d+\+)?([a-z0-9-]+)@users\.noreply\.github\.com$", e)
    if m:
        return m.group(1)
    return None


def _developer_identity_norm_tokens(dev: Developer) -> set:
    tokens = set()
    for alias in (dev.aliases or []):
        norm = _normalize_identity_text(alias)
        if norm:
            tokens.add(norm)
    emails = list(dev.emails or [])
    if "@" in str(dev.id or ""):
        emails.append(str(dev.id or ""))
    for email in emails:
        local = str(email or "").split("@", 1)[0].split("+")[-1]
        norm = _normalize_identity_text(local)
        if norm:
            tokens.add(norm)
        login = _extract_login_from_noreply(str(email or ""))
        if login:
            login_norm = _normalize_identity_text(login)
            if login_norm:
                tokens.add(login_norm)
    return tokens


def _resolve_dev_id_from_login(login: str, login_to_dev_id: Dict[str, str]) -> Optional[str]:
    raw = str(login or "").strip().lower()
    if not raw:
        return None
    direct = login_to_dev_id.get(raw)
    if direct:
        return direct
    normalized = _normalize_identity_text(raw)
    if normalized:
        return login_to_dev_id.get(f"norm:{normalized}") or login_to_dev_id.get(normalized)
    return None


def _augment_login_to_dev_id_map_with_github_contributors(
    project_url: str,
    developers: List[Developer],
    mapping: Dict[str, str],
    http_cache: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    owner, repo = _parse_github_owner_repo(project_url)
    if not owner or not repo or not developers:
        return mapping

    token = _effective_github_token()
    timeout_sec = _read_int_env("GITHUB_HTTP_TIMEOUT_SEC", 6, 1)
    contributor_logins: List[str] = []

    page = 1
    while True:
        payload = _github_get_json(
            f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/contributors?per_page=100&page={page}",
            token,
            timeout_sec,
            http_cache,
        )
        if not isinstance(payload, list) or not payload:
            break
        for item in payload:
            if not isinstance(item, dict):
                continue
            login = str(item.get("login") or "").strip().lower()
            if login and login not in contributor_logins:
                contributor_logins.append(login)
        page += 1

    if not contributor_logins:
        return mapping

    norm_to_dev_ids: Dict[str, set] = {}
    for dev in developers:
        for token_norm in _developer_identity_norm_tokens(dev):
            norm_to_dev_ids.setdefault(token_norm, set()).add(dev.id)

    for login in contributor_logins:
        if login in mapping:
            continue
        norm = _normalize_identity_text(login)
        if not norm:
            continue
        dev_ids = norm_to_dev_ids.get(norm) or set()
        if len(dev_ids) == 1:
            mapping[login] = next(iter(dev_ids))

    return mapping


def _parse_github_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # GitHub dates are UTC like 2020-01-01T12:34:56Z
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _build_login_to_dev_id_map(developers: List[Developer]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    normalized_candidates: Dict[str, set] = {}
    for dev in developers:
        aliases_norm = {_normalize_identity_text(a) for a in (dev.aliases or []) if a}
        for email in dev.emails or []:
            login = _extract_login_from_noreply(email)
            if login:
                mapping[login.lower()] = dev.id
                normalized_candidates.setdefault(_normalize_identity_text(login), set()).add(dev.id)
            local = (email or "").split("@", 1)[0].split("+")[-1].strip().lower()
            local_norm = _normalize_identity_text(local)
            if local_norm:
                normalized_candidates.setdefault(local_norm, set()).add(dev.id)
            if local and re.match(r"^[a-z0-9-]{1,39}$", local):
                if _normalize_identity_text(local) in aliases_norm:
                    mapping[local] = dev.id
        for alias in dev.aliases or []:
            alias_s = (alias or "").strip().lower()
            if alias_s and re.match(r"^[a-z0-9-]{1,39}$", alias_s):
                mapping.setdefault(alias_s, dev.id)
            alias_norm = _normalize_identity_text(alias_s)
            if alias_norm:
                normalized_candidates.setdefault(alias_norm, set()).add(dev.id)
        if "@" in str(dev.id or ""):
            id_local = str(dev.id).split("@", 1)[0].split("+")[-1].strip().lower()
            id_norm = _normalize_identity_text(id_local)
            if id_norm:
                normalized_candidates.setdefault(id_norm, set()).add(dev.id)
    for norm_key, dev_ids in normalized_candidates.items():
        if norm_key and len(dev_ids) == 1:
            mapping.setdefault(f"norm:{norm_key}", next(iter(dev_ids)))
    return mapping


def _fetch_github_issue_pr_data(
    project_url: str,
    start: datetime,
    end_exclusive: datetime,
    login_to_dev_id: Dict[str, str],
    http_cache: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Tuple[str, str, datetime]], List[Dict[str, Any]]]:
    owner, repo = _parse_github_owner_repo(project_url)
    if not owner or not repo:
        return [], []

    token = _effective_github_token()
    timeout_sec = _read_int_env("GITHUB_HTTP_TIMEOUT_SEC", 6, 1)
    fetch_workers = _read_parallelism_env("GITHUB_FETCH_PARALLELISM", _adaptive_github_parallelism())
    repo_web = _github_repo_web_base(project_url)

    def add_pairwise_interactions(
        participants: set,
        ts: datetime,
        out: List[Tuple[str, str, datetime]],
        seen: set,
    ) -> None:
        resolved_ids = []
        for participant in participants:
            dev_id = _resolve_dev_id_from_login(participant, login_to_dev_id)
            if dev_id:
                resolved_ids.append(dev_id)
        ids = sorted(set(resolved_ids))
        if len(ids) < 2:
            return
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                key = (a, b, ts.date().isoformat())
                if key in seen:
                    continue
                seen.add(key)
                out.append((a, b, ts))
                out.append((b, a, ts))

    def add_signal(
        out: List[Dict[str, Any]],
        login: str,
        ts: Optional[datetime],
        parts: List[str],
        *,
        source_id: str,
        source_label: str,
        source_url: str,
        source_type: str,
        is_open: bool,
        thread_id: str,
        thread_label: str,
        thread_url: str,
        thread_is_open: bool,
    ) -> None:
        if not ts or ts < start or ts >= end_exclusive:
            return
        dev_id = _resolve_dev_id_from_login(login, login_to_dev_id)
        if not dev_id:
            return
        text = " ".join(x.strip() for x in parts if isinstance(x, str) and x.strip())
        if text:
            out.append({
                "developer_id": dev_id,
                "timestamp": ts,
                "text": text[:3000],
                "source_id": source_id,
                "source_label": source_label[:180],
                "source_url": source_url,
                "source_type": source_type,
                "is_open": bool(is_open),
                "thread_id": thread_id,
                "thread_label": thread_label[:180],
                "thread_url": thread_url,
                "thread_is_open": bool(thread_is_open),
            })

    since_iso = start.isoformat() + "Z"
    issues: List[Dict[str, Any]] = []
    page = 1
    while True:
        payload = _github_get_json(
            f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/issues"
            f"?state=all&since={quote(since_iso)}&per_page=100&page={page}&sort=updated&direction=asc",
            token,
            timeout_sec,
            http_cache,
        )
        if not isinstance(payload, list) or not payload:
            break
        for issue in payload:
            if isinstance(issue, dict):
                issues.append(issue)
        page += 1

    if not issues:
        return [], []

    def process_issue(issue: Dict[str, Any]) -> Tuple[List[Tuple[str, str, datetime]], List[Dict[str, Any]]]:
        local_interactions: List[Tuple[str, str, datetime]] = []
        local_signals: List[Dict[str, Any]] = []
        local_seen = set()

        number = issue.get("number")
        if not number:
            return local_interactions, local_signals

        issue_ts = _parse_github_datetime(issue.get("updated_at") or issue.get("created_at"))
        if not issue_ts or issue_ts < start or issue_ts >= end_exclusive:
            return local_interactions, local_signals

        is_pr = "pull_request" in issue
        thread_type = "pr" if is_pr else "issue"
        thread_id = f"{thread_type}:{number}"
        issue_title = str(issue.get("title") or f"{thread_type.upper()} #{number}")
        thread_label = f"{'PR' if is_pr else 'Issue'} #{number}: {issue_title}"
        thread_url = str(issue.get("html_url") or f"{repo_web}/{ 'pull' if is_pr else 'issues' }/{number}")
        thread_is_open = str(issue.get("state") or "").strip().lower() == "open"

        participants = set()
        iu = issue.get("user") or {}
        ilogin = str(iu.get("login") or "").strip()
        if ilogin:
            participants.add(ilogin)

        for assignee in issue.get("assignees") or []:
            if isinstance(assignee, dict):
                assignee_login = str(assignee.get("login") or "").strip()
                if assignee_login:
                    participants.add(assignee_login)

        add_signal(
            local_signals,
            ilogin,
            issue_ts,
            [str(issue.get("title") or ""), str(issue.get("body") or "")],
            source_id=thread_id,
            source_label=thread_label,
            source_url=thread_url,
            source_type="pull_request" if is_pr else "issue",
            is_open=thread_is_open,
            thread_id=thread_id,
            thread_label=thread_label,
            thread_url=thread_url,
            thread_is_open=thread_is_open,
        )

        comments = _github_get_json(
            f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/issues/{number}/comments?per_page=100",
            token,
            timeout_sec,
            http_cache,
        )
        if isinstance(comments, list):
            for c in comments:
                if not isinstance(c, dict):
                    continue
                cts = _parse_github_datetime(c.get("created_at"))
                if not cts or cts < start or cts >= end_exclusive:
                    continue
                cu = c.get("user") or {}
                clogin = str(cu.get("login") or "").strip()
                if clogin:
                    participants.add(clogin)
                    add_pairwise_interactions(participants, cts, local_interactions, local_seen)
                comment_id = str(c.get("id") or "")
                add_signal(
                    local_signals,
                    clogin,
                    cts,
                    [str(c.get("body") or "")],
                    source_id=f"{thread_id}:comment:{comment_id or 'x'}",
                    source_label=f"{thread_label} comment",
                    source_url=str(c.get("html_url") or thread_url),
                    source_type="issue_comment",
                    is_open=thread_is_open,
                    thread_id=thread_id,
                    thread_label=thread_label,
                    thread_url=thread_url,
                    thread_is_open=thread_is_open,
                )

        if is_pr:
            reviews = _github_get_json(
                f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/pulls/{number}/reviews?per_page=100",
                token,
                timeout_sec,
                http_cache,
            )
            if isinstance(reviews, list):
                for r in reviews:
                    if not isinstance(r, dict):
                        continue
                    rts = _parse_github_datetime(r.get("submitted_at") or r.get("created_at"))
                    if not rts or rts < start or rts >= end_exclusive:
                        continue
                    ru = r.get("user") or {}
                    rlogin = str(ru.get("login") or "").strip()
                    if rlogin:
                        participants.add(rlogin)
                        add_pairwise_interactions(participants, rts, local_interactions, local_seen)
                    add_signal(
                        local_signals,
                        rlogin,
                        rts,
                        [str(r.get("state") or ""), str(r.get("body") or "")],
                        source_id=f"{thread_id}:review:{str(r.get('id') or 'x')}",
                        source_label=f"{thread_label} review",
                        source_url=str(r.get("html_url") or thread_url),
                        source_type="review",
                        is_open=thread_is_open,
                        thread_id=thread_id,
                        thread_label=thread_label,
                        thread_url=thread_url,
                        thread_is_open=thread_is_open,
                    )

            pr_comments = _github_get_json(
                f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/pulls/{number}/comments?per_page=100",
                token,
                timeout_sec,
                http_cache,
            )
            if isinstance(pr_comments, list):
                for c in pr_comments:
                    if not isinstance(c, dict):
                        continue
                    pts = _parse_github_datetime(c.get("created_at"))
                    if not pts or pts < start or pts >= end_exclusive:
                        continue
                    pu = c.get("user") or {}
                    plogin = str(pu.get("login") or "").strip()
                    if plogin:
                        participants.add(plogin)
                        add_pairwise_interactions(participants, pts, local_interactions, local_seen)
                    add_signal(
                        local_signals,
                        plogin,
                        pts,
                        [str(c.get("body") or "")],
                        source_id=f"{thread_id}:pr_comment:{str(c.get('id') or 'x')}",
                        source_label=f"{thread_label} inline comment",
                        source_url=str(c.get("html_url") or thread_url),
                        source_type="pr_comment",
                        is_open=thread_is_open,
                        thread_id=thread_id,
                        thread_label=thread_label,
                        thread_url=thread_url,
                        thread_is_open=thread_is_open,
                    )

        add_pairwise_interactions(participants, issue_ts, local_interactions, local_seen)
        return local_interactions, local_signals

    interactions: List[Tuple[str, str, datetime]] = []
    signals: List[Dict[str, Any]] = []
    seen = set()

    workers = min(len(issues), max(1, fetch_workers))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(process_issue, issue) for issue in issues]
        for fut in as_completed(futures):
            try:
                issue_interactions, issue_signals = fut.result()
            except Exception:
                continue
            for item in issue_interactions:
                key = (item[0], item[1], item[2].date().isoformat())
                if key in seen:
                    continue
                seen.add(key)
                interactions.append(item)
            signals.extend(issue_signals)

    interactions.sort(key=lambda x: x[2])
    signals.sort(key=lambda x: x.get("timestamp") or datetime.min)
    return interactions, signals


def _fetch_github_issue_pr_interactions(
    project_url: str,
    start: datetime,
    end_exclusive: datetime,
    login_to_dev_id: Dict[str, str],
    http_cache: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str, datetime]]:
    interactions, _ = _fetch_github_issue_pr_data(
        project_url,
        start,
        end_exclusive,
        login_to_dev_id,
        http_cache=http_cache,
    )
    return interactions


def _fetch_github_issue_pr_text_signals(
    project_url: str,
    start: datetime,
    end_exclusive: datetime,
    login_to_dev_id: Dict[str, str],
    http_cache: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    _, signals = _fetch_github_issue_pr_data(
        project_url,
        start,
        end_exclusive,
        login_to_dev_id,
        http_cache=http_cache,
    )
    return signals


def _infer_gender_from_bio(bio: str, pronoun_sets: Dict[str, set]) -> Tuple[str, float, List[str]]:
    if not bio:
        return "Unknown", 0.0, []

    txt = bio.lower()
    compact = re.sub(r"\s+", " ", txt).strip()
    if any(p in compact for p in _NO_PRONOUN_PHRASES):
        return "No-pronoun", 0.95, []

    category_hits: Dict[str, set] = {"man": set(), "woman": set(), "neutral": set()}
    source_map = {
        "man": {"masculine"},
        "woman": {"feminine"},
        "neutral": {"neutral", "neopronouns", "nounself", "numberself", "nameself"},
    }
    all_detected: set = set()

    for category, source_keys in source_map.items():
        for source_key in source_keys:
            for token in pronoun_sets.get(source_key, set()):
                if not token:
                    continue
                if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", txt):
                    category_hits[category].add(token)
                    all_detected.add(token)

    explicit_pronouns = bool(re.search(r"\bpronouns?\b", txt))
    slash_pronouns = bool(re.search(r"\b[a-z0-9]+/[a-z0-9]+(?:/[a-z0-9]+)?\b", txt))
    active_categories = [k for k, v in category_hits.items() if v]

    if not active_categories:
        return "Unknown", 0.0, []

    base_conf = 0.62
    if slash_pronouns:
        base_conf += 0.17
    if explicit_pronouns:
        base_conf += 0.17

    if len(active_categories) > 1:
        return "Multi-pronoun", round(min(0.98, base_conf + 0.06), 2), sorted(all_detected)
    if active_categories[0] == "man":
        return "Man", round(min(0.98, base_conf), 2), sorted(all_detected)
    if active_categories[0] == "woman":
        return "Woman", round(min(0.98, base_conf), 2), sorted(all_detected)
    return "Non-binary", round(min(0.98, base_conf), 2), sorted(all_detected)


class GitHubGenderResolver:
    def __init__(self, project_url: str):
        self.owner, self.repo = _parse_github_owner_repo(project_url)
        self.pronoun_sets = _load_pronoun_sets()
        self.timeout_sec = 4
        self.github_token = _effective_github_token()
        self.max_profile_lookups = max(0, int(os.environ.get("GITHUB_PROFILE_LOOKUP_LIMIT", "120")))
        self.lookup_count = 0
        self.user_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self.contributor_logins: Optional[List[str]] = None

    def _get_json(self, url: str) -> Optional[Any]:
        return _github_get_json(
            url,
            self.github_token,
            self.timeout_sec,
            cache=self.user_cache,
            use_persistent_cache=True
        )

    def _fetch_user(self, login: str) -> Optional[Dict[str, Any]]:
        login = (login or "").strip()
        if not login:
            return None
        if login in self.user_cache:
            return self.user_cache[login]
        if self.max_profile_lookups and self.lookup_count >= self.max_profile_lookups:
            self.user_cache[login] = None
            return None

        self.lookup_count += 1
        payload = self._get_json(f"https://api.github.com/users/{quote(login)}")
        user = payload if isinstance(payload, dict) else None
        self.user_cache[login] = user
        return user

    def _load_contributor_logins(self) -> List[str]:
        if self.contributor_logins is not None:
            return self.contributor_logins

        self.contributor_logins = []
        if not self.owner or not self.repo:
            return self.contributor_logins

        page = 1
        while True:
            payload = self._get_json(
                f"https://api.github.com/repos/{quote(self.owner)}/{quote(self.repo)}/contributors?per_page=100&page={page}"
            )
            if not isinstance(payload, list) or not payload:
                break
            for item in payload:
                if not isinstance(item, dict):
                    continue
                login = str(item.get("login", "")).strip()
                if login and login not in self.contributor_logins:
                    self.contributor_logins.append(login)
            page += 1

        return self.contributor_logins

    def _build_candidate_logins(self, dev: Developer) -> List[str]:
        candidates: List[str] = []
        seen = set()

        def add(login: Optional[str]):
            key = (login or "").strip()
            if not key or key in seen:
                return
            seen.add(key)
            candidates.append(key)

        emails = list(dev.emails or [])
        if "@" in dev.id:
            emails.append(dev.id)

        for e in emails:
            add(_extract_login_from_noreply(e))

        for alias in dev.aliases or []:
            raw = (alias or "").strip()
            if not raw:
                continue
            if re.match(r"^[a-z0-9-]{1,39}$", raw.lower()):
                add(raw.lower())

        alias_norm = {_normalize_identity_text(a) for a in dev.aliases or [] if a}
        if alias_norm:
            for login in self._load_contributor_logins():
                if _normalize_identity_text(login) in alias_norm:
                    add(login)

        return candidates

    def _score_user_match(self, dev: Developer, login: str, user: Optional[Dict[str, Any]]) -> int:
        aliases_norm = {_normalize_identity_text(a) for a in dev.aliases or [] if a}
        score = 0
        login_norm = _normalize_identity_text(login)
        if login_norm in aliases_norm:
            score += 4

        for e in (dev.emails or []):
            local_norm = _normalize_identity_text(e.split("@", 1)[0].split("+")[-1])
            if local_norm and local_norm == login_norm:
                score += 2

        if not user:
            return score

        user_login_norm = _normalize_identity_text(str(user.get("login", "")))
        user_name_norm = _normalize_identity_text(str(user.get("name", "")))
        if user_login_norm in aliases_norm:
            score += 4
        if user_name_norm and user_name_norm in aliases_norm:
            score += 5
        return score

    def _resolve_user(self, dev: Developer) -> Optional[Dict[str, Any]]:
        candidates = self._build_candidate_logins(dev)
        if not candidates:
            return None

        best_score = -1
        best_user = None
        for login in candidates:
            user = self._fetch_user(login)
            score = self._score_user_match(dev, login, user)
            if score > best_score:
                best_score = score
                best_user = user
        return best_user if best_score > 0 else None

    def annotate_developer(self, dev: Developer) -> None:
        dev.gender = "Unknown"
        dev.gender_confidence = 0.0
        dev.gender_source = "none"
        dev.pronouns_detected = []

        user = self._resolve_user(dev)
        if not user:
            return

        bio = str(user.get("bio") or "").strip()
        if not bio:
            dev.gender_source = "github_profile_no_bio"
            return

        gender, confidence, pronouns = _infer_gender_from_bio(bio, self.pronoun_sets)
        dev.gender = gender
        dev.gender_confidence = confidence
        dev.pronouns_detected = pronouns
        dev.gender_source = "github_bio_pronouns" if gender != "Unknown" else "github_bio_unresolved"

    def annotate_developers(self, developers: List[Developer]) -> None:
        unique_logins: List[str] = []
        seen = set()
        for dev in developers:
            for login in self._build_candidate_logins(dev):
                if login not in seen:
                    seen.add(login)
                    unique_logins.append(login)

        if self.max_profile_lookups:
            unique_logins = unique_logins[: self.max_profile_lookups]

        if unique_logins:
            workers = min(
                len(unique_logins),
                _read_parallelism_env("GITHUB_PROFILE_PARALLELISM", _adaptive_github_parallelism()),
            )
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                futures = {
                    pool.submit(self._get_json, f"https://api.github.com/users/{quote(login)}"): login
                    for login in unique_logins
                }
                for fut in as_completed(futures):
                    login = futures[fut]
                    try:
                        payload = fut.result()
                    except Exception:
                        payload = None
                    self.user_cache[login] = payload if isinstance(payload, dict) else None

            self.lookup_count = len(self.user_cache)

        for dev in developers:
            self.annotate_developer(dev)


def _build_email_to_dev_id(developers: List[Developer]) -> Dict[str, str]:
    email_to_dev_id: Dict[str, str] = {}
    for dev in developers:
        for email in dev.emails:
            if email:
                email_to_dev_id[email.lower()] = dev.id
    return email_to_dev_id


def _fill_developer_stats(developers: List[Developer], commits: List[Commit], rszz_counts: Dict[str, int]):
    dev_stats: Dict[str, Dict[str, object]] = {}
    for dev in developers:
        dev_stats[dev.id] = {
            "commits_count": 0,
            "bug_fix_commits_count": 0,
            "files_touched": set(),
            "lines_added": 0,
            "lines_deleted": 0,
        }

    for c in commits:
        st = dev_stats.get(c.author_id)
        if not st:
            continue
        st["commits_count"] = int(st["commits_count"]) + 1
        if c.is_bug_fix:
            st["bug_fix_commits_count"] = int(st["bug_fix_commits_count"]) + 1
        files = st["files_touched"]
        if isinstance(files, set):
            files.update(c.files_modified)
        st["lines_added"] = int(st["lines_added"]) + int(c.lines_added or 0)
        st["lines_deleted"] = int(st["lines_deleted"]) + int(c.lines_deleted or 0)

    for dev in developers:
        st = dev_stats.get(dev.id, {})
        commits_count = int(st.get("commits_count", 0))
        files_touched = st.get("files_touched", set())
        lines_added = int(st.get("lines_added", 0))
        lines_deleted = int(st.get("lines_deleted", 0))

        dev.commits_count = commits_count
        dev.bug_fix_commits_count = int(st.get("bug_fix_commits_count", 0))
        dev.files_touched_count = len(files_touched) if isinstance(files_touched, set) else 0
        dev.lines_added = lines_added
        dev.lines_deleted = lines_deleted
        dev.code_churn = lines_added + lines_deleted
        dev.avg_files_per_commit = round(
            (dev.files_touched_count / commits_count) if commits_count > 0 else 0.0,
            2,
        )
        dev.bug_introduced_count = int(rszz_counts.get(dev.id, 0))


def _safe_div(num: float, den: float) -> float:
    if not den:
        return 0.0
    try:
        return float(num) / float(den)
    except Exception:
        return 0.0


def _estimate_window_eta_seconds(
    project: Project,
    started_windows_at: datetime,
    processed_windows: int,
    total_windows: int,
) -> Optional[int]:
    if total_windows <= 0:
        return None
    remaining = max(total_windows - processed_windows, 0)
    if remaining <= 0:
        return 0

    sec_per_window: Optional[float] = None
    if processed_windows > 0:
        elapsed = max((datetime.now() - started_windows_at).total_seconds(), 1.0)
        sec_per_window = elapsed / float(processed_windows)
    elif (project.last_analysis_duration_seconds or 0) > 0 and (project.last_analysis_window_count or 0) > 0:
        sec_per_window = float(project.last_analysis_duration_seconds) / float(project.last_analysis_window_count)
    else:
        sec_per_window = float(os.environ.get("ANALYSIS_DEFAULT_SEC_PER_WINDOW", "25"))

    eta = int(max(5, round(remaining * max(sec_per_window, 1.0))))
    return min(eta, 72 * 3600)


def _set_analysis_progress(
    project: Project,
    progress_pct: float,
    eta_seconds: Optional[int],
    window_index: int,
    window_total: int,
) -> None:
    project.analysis_progress_pct = max(0.0, min(100.0, float(progress_pct)))
    project.analysis_eta_seconds = int(eta_seconds) if eta_seconds is not None else None
    project.analysis_window_index = max(0, int(window_index))
    project.analysis_window_total = max(0, int(window_total))


def _avg_mapping_value(values: Dict[str, float]) -> float:
    if not values:
        return 0.0
    return _safe_div(sum(float(v) for v in values.values()), len(values))


def _undirected_pairs(graph: nx.Graph) -> set:
    return {tuple(sorted((str(u), str(v)))) for u, v in graph.edges()}


def _modularity_score(graph: nx.Graph) -> float:
    if graph.number_of_nodes() < 2 or graph.number_of_edges() == 0:
        return 0.0
    try:
        communities = list(nx.community.greedy_modularity_communities(graph))
        if not communities:
            return 0.0
        return float(nx.community.modularity(graph, communities))
    except Exception:
        return 0.0


def _average_reciprocal_distance(graph: nx.Graph) -> float:
    if graph.number_of_nodes() < 2:
        return 0.0

    total = 0.0
    count = 0
    for component in nx.connected_components(graph):
        sub = graph.subgraph(component)
        if sub.number_of_nodes() < 2:
            continue
        shortest = dict(nx.all_pairs_shortest_path_length(sub))
        nodes = sorted(sub.nodes())
        for i, u in enumerate(nodes):
            for v in nodes[i + 1:]:
                d = shortest.get(u, {}).get(v)
                if d and d > 0:
                    total += 1.0 / float(d)
                    count += 1
    return _safe_div(total, count)


def _core_developers_from_commits(commits: List[Commit], coverage: float = 0.80) -> set:
    counts: Dict[str, int] = {}
    for c in commits:
        if not c.author_id:
            continue
        counts[c.author_id] = counts.get(c.author_id, 0) + 1

    total = sum(counts.values())
    if total <= 0:
        return set()

    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    threshold = float(total) * coverage
    acc = 0
    core = set()
    for dev_id, cnt in ranked:
        core.add(dev_id)
        acc += cnt
        if acc >= threshold:
            break
    return core


def _sponsored_developers(commits: List[Commit]) -> set:
    by_dev: Dict[str, List[Commit]] = {}
    for c in commits:
        if c.author_id:
            by_dev.setdefault(c.author_id, []).append(c)

    sponsored = set()
    for dev_id, rows in by_dev.items():
        total = len(rows)
        if total <= 0:
            continue

        work_commits = 0
        for c in rows:
            dt = c.date
            if dt.weekday() < 5 and 9 <= dt.hour < 18:
                work_commits += 1

        if _safe_div(work_commits, total) >= 0.95:
            sponsored.add(dev_id)

    return sponsored


def _distinct_time_zones(commits: List[Commit]) -> int:
    # Uses most frequent tz offset per developer (if available in commit metadata).
    offsets_by_dev: Dict[str, Dict[int, int]] = {}
    for c in commits:
        if not c.author_id or c.tz_offset_minutes is None:
            continue
        dev_map = offsets_by_dev.setdefault(c.author_id, {})
        offset = int(c.tz_offset_minutes)
        dev_map[offset] = dev_map.get(offset, 0) + 1

    representative_offsets = set()
    for offset_counts in offsets_by_dev.values():
        top_offset = sorted(offset_counts.items(), key=lambda x: (-x[1], x[0]))[0][0]
        representative_offsets.add(top_offset)

    return len(representative_offsets)


def _build_proxy_communication_interactions(commits: List[Commit]) -> List[Tuple[str, str, datetime]]:
    # Fallback communication proxy when explicit communication data is unavailable.
    # Rule: developers active on the same UTC day are considered to have an interaction.
    by_day: Dict[str, set] = {}
    for c in commits:
        if not c.author_id:
            continue
        day_key = c.date.strftime("%Y-%m-%d")
        by_day.setdefault(day_key, set()).add(c.author_id)

    interactions: List[Tuple[str, str, datetime]] = []
    seen = set()

    for day, authors in by_day.items():
        sorted_authors = sorted(authors)
        if len(sorted_authors) < 2:
            continue
        dt = datetime.fromisoformat(f"{day}T12:00:00")
        for i, sender in enumerate(sorted_authors):
            for receiver in sorted_authors[i + 1:]:
                key1 = (sender, receiver, day)
                key2 = (receiver, sender, day)
                if key1 not in seen:
                    interactions.append((sender, receiver, dt))
                    seen.add(key1)
                if key2 not in seen:
                    interactions.append((receiver, sender, dt))
                    seen.add(key2)

    return interactions


def _compute_table3_metrics(
    commits: List[Commit],
    nb: NetworkBuilder,
    community_smells: List[SmellInstance],
    prev_state: Optional[Dict[str, set]],
) -> Tuple[Dict[str, Any], Dict[str, set]]:
    commit_authors = {c.author_id for c in commits if c.author_id}
    collab_nodes = {str(n) for n in nb.collaboration_graph.nodes()} | commit_authors
    comm_nodes = {str(n) for n in nb.communication_graph.nodes()}
    global_nodes = set(collab_nodes | comm_nodes)

    devs = len(global_nodes)
    ml_only = len(comm_nodes - collab_nodes)
    code_only = len(collab_nodes - comm_nodes)
    ml_code = len(comm_nodes & collab_nodes)

    sponsored = _sponsored_developers(commits)
    core_base = _core_developers_from_commits(commits, coverage=0.80)
    core_global = core_base & global_nodes
    core_mail = core_base & comm_nodes
    core_code = core_base & collab_nodes
    sponsored_core = sponsored & core_code

    needs = _undirected_pairs(nb.collaboration_graph)
    actual_comm = _undirected_pairs(nb.communication_graph)
    st_congruence = _safe_div(len(needs & actual_comm), len(needs))

    global_graph = nx.Graph()
    global_graph.add_nodes_from(global_nodes)
    global_graph.add_edges_from(needs)
    global_graph.add_edges_from(actual_comm)

    smelly_devs = {
        str(dev_id)
        for s in community_smells
        for dev_id in (s.affected_entities or [])
        if str(dev_id) in global_nodes
    }

    closeness_map = nx.closeness_centrality(global_graph) if global_graph.number_of_nodes() > 1 else {}
    betweenness_map = nx.betweenness_centrality(global_graph, normalized=True) if global_graph.number_of_nodes() > 1 else {}
    degree_map = nx.degree_centrality(global_graph) if global_graph.number_of_nodes() > 1 else {}

    global_turnover = 0.0
    code_turnover = 0.0
    core_global_turnover = 0.0
    core_mail_turnover = 0.0
    core_code_turnover = 0.0
    ratio_smelly_quitters = 0.0

    if prev_state:
        prev_global = prev_state.get("global_nodes", set())
        prev_collab = prev_state.get("collab_nodes", set())
        prev_core_global = prev_state.get("core_global", set())
        prev_core_mail = prev_state.get("core_mail", set())
        prev_core_code = prev_state.get("core_code", set())
        prev_smelly = prev_state.get("smelly_devs", set())

        global_turnover = _safe_div(len(prev_global - global_nodes), len(prev_global))
        code_turnover = _safe_div(len(prev_collab - collab_nodes), len(prev_collab))
        core_global_turnover = _safe_div(len(prev_core_global - core_global), len(prev_core_global))
        core_mail_turnover = _safe_div(len(prev_core_mail - core_mail), len(prev_core_mail))
        core_code_turnover = _safe_div(len(prev_core_code - core_code), len(prev_core_code))
        ratio_smelly_quitters = _safe_div(len(prev_smelly - global_nodes), len(prev_smelly))

    metrics: Dict[str, Any] = {
        # Section 1
        "devs": devs,
        "ml.only.devs": ml_only,
        "code.only.devs": code_only,
        "ml.code.devs": ml_code,
        "perc.ml.only.devs": round(_safe_div(ml_only, devs), 6),
        "perc.code.only.devs": round(_safe_div(code_only, devs), 6),
        "perc.ml.code.devs": round(_safe_div(ml_code, devs), 6),
        "sponsored.devs": len(sponsored),
        "ratio.sponsored": round(_safe_div(len(sponsored), len(collab_nodes)), 6),
        # Section 2
        "st.congruence": round(st_congruence, 6),
        "communicability": round(_average_reciprocal_distance(global_graph), 6),
        "num.tz": _distinct_time_zones(commits),
        "ratio.smelly.devs": round(_safe_div(len(smelly_devs), devs), 6),
        # Section 3
        "core.global.devs": len(core_global),
        "core.mail.devs": len(core_mail),
        "core.code.devs": len(core_code),
        "sponsored.core.devs": len(sponsored_core),
        "ratio.sponsored.core": round(_safe_div(len(sponsored_core), len(core_code)), 6),
        "global.truck": round(_safe_div(len(global_nodes - core_global), len(global_nodes)), 6),
        "mail.truck": round(_safe_div(len(comm_nodes - core_mail), len(comm_nodes)), 6),
        "code.truck": round(_safe_div(len(collab_nodes - core_code), len(collab_nodes)), 6),
        # Section 4
        "global.turnover": round(global_turnover, 6),
        "code.turnover": round(code_turnover, 6),
        "core.global.turnover": round(core_global_turnover, 6),
        "core.mail.turnover": round(core_mail_turnover, 6),
        "core.code.turnover": round(core_code_turnover, 6),
        "ratio.smelly.quitters": round(ratio_smelly_quitters, 6),
        # Section 5
        "closeness.centr": round(_avg_mapping_value(closeness_map), 6),
        "betweenness.centr": round(_avg_mapping_value(betweenness_map), 6),
        "degree.centr": round(_avg_mapping_value(degree_map), 6),
        "global.mod": round(_modularity_score(global_graph), 6),
        "mail.mod": round(_modularity_score(nb.communication_graph), 6),
        "code.mod": round(_modularity_score(nb.collaboration_graph), 6),
        "density": round(float(nx.density(global_graph)) if global_graph.number_of_nodes() > 1 else 0.0, 6),
    }

    new_state = {
        "global_nodes": set(global_nodes),
        "collab_nodes": set(collab_nodes),
        "comm_nodes": set(comm_nodes),
        "core_global": set(core_global),
        "core_mail": set(core_mail),
        "core_code": set(core_code),
        "smelly_devs": set(smelly_devs),
    }
    return metrics, new_state


def _resolve_window(project: Project, window_id: Optional[str]) -> Optional[ProjectTimeWindow]:
    if not project.time_windows:
        return None

    if window_id:
        for w in project.time_windows:
            if w.id == window_id:
                return w

    if project.active_time_window_id:
        for w in project.time_windows:
            if w.id == project.active_time_window_id:
                return w

    return project.time_windows[-1]


def _validate_time_windows(windows: List[ProjectTimeWindow]) -> None:
    prev_start: Optional[datetime] = None
    for w in windows:
        if prev_start and w.start_date < prev_start:
            raise ValueError(f"Time windows are not sorted chronologically: {w.id}")
        prev_start = w.start_date

        m = w.metrics
        if int(m.loc or 0) < 0 or int(m.nom or 0) < 0:
            raise ValueError(f"Negative LOC/NOM in window {w.id}")

        dev_count = len(w.developers or [])
        for e in w.collaboration_edges or []:
            try:
                frm = int(e.get("from"))
                to = int(e.get("to"))
                weight = int(e.get("weight", 1))
            except Exception as ex:
                raise ValueError(f"Invalid edge payload in window {w.id}: {e}") from ex
            if frm < 0 or frm >= dev_count or to < 0 or to >= dev_count:
                raise ValueError(f"Edge index out of bounds in window {w.id}: {e}")
            if weight <= 0:
                raise ValueError(f"Edge weight must be > 0 in window {w.id}: {e}")


def _ensure_project_repo_available(project: Project) -> None:
    repo_path = project.local_path
    git_dir = os.path.join(repo_path, ".git")
    if os.path.isdir(repo_path) and os.path.isdir(git_dir):
        return

    if not project.url:
        raise FileNotFoundError(f"Repository not found at {repo_path} and no URL is configured.")

    os.makedirs(os.path.dirname(repo_path), exist_ok=True)
    if os.path.isdir(repo_path) and not os.path.isdir(git_dir):
        raise RuntimeError(
            f"Path exists but is not a git repository: {repo_path}. "
            "Delete the folder or update project path, then retry."
        )

    try:
        _git_clone_with_timeout(project.url, repo_path)
    except ValueError as e:
        raise FileNotFoundError(str(e)) from e
    except Exception as e:
        raise RuntimeError(
            f"Failed to clone repository from {project.url} to {repo_path}. {e}"
        ) from e


def _clone_repo_for_history(source_repo_path: str) -> str:
    clone_dir = tempfile.mkdtemp(prefix="history_repo_")
    cmd = ["git", "clone", "--quiet", "--no-checkout", source_repo_path, clone_dir]
    subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return clone_dir


def _checkout_ref(repo_path: str, ref: str) -> None:
    cmd = ["git", "-C", repo_path, "checkout", "--quiet", ref]
    subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _load_snapshot_cache(project_id: str) -> Dict[str, Any]:
    cache_path = os.path.join(PROJECTS_ROOT, f"{project_id}_snapshots.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading snapshot cache for {project_id}: {e}")
    return {}


def _save_snapshot_cache(project_id: str, cache: Dict[str, Any]) -> None:
    cache_path = os.path.join(PROJECTS_ROOT, f"{project_id}_snapshots.json")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=4)
    except Exception as e:
        print(f"Error saving snapshot cache for {project_id}: {e}")


def _compute_loc_nom_for_snapshot(repo_path: str) -> Tuple[int, int]:
    loc = 0
    nom = 0
    skipped_dirs = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
    }

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skipped_dirs]
        for name in files:
            if not name.endswith(".py"):
                continue
            file_path = os.path.join(root, name)
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    src = f.read() or ""
            except Exception:
                continue

            loc += len(src.splitlines())
            try:
                tree = ast.parse(src)
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nom += 1

    return loc, nom


def _to_repo_relative_path(file_path: Optional[str], repo_path: str) -> str:
    if not file_path:
        return "Unknown"
    try:
        if os.path.isabs(file_path):
            return os.path.relpath(file_path, repo_path)
        return file_path
    except Exception:
        return file_path or "Unknown"


def _analyze_snapshot_worker(
    project_local_path_for_clone: str,
    snapshot_hash: str,
    email_to_dev_id: Dict[str, str],
    base_dev_by_id: Dict[str, Developer],
    dpy_binary: Optional[str],
    vulnerabilities_enabled: bool,
) -> Dict[str, Any]:
    if not snapshot_hash:
        return {
            "ml_enriched": [],
            "traditional_enriched": [],
            "vulnerabilities_enriched": [],
            "loc": 0,
            "nom": 0,
            "ml_status": "No commit hash",
            "ml_error": None,
            "ml_stdout": None,
            "ml_stderr": None,
            "ml_call_graph_nodes": [],
            "ml_call_graph_edges": [],
        }

    repo_path = _clone_repo_for_history(project_local_path_for_clone)
    try:
        _checkout_ref(repo_path, snapshot_hash)

        # Instantiate analyzers for this worker
        ml_analyzer = MLSmellAnalyzer(os.path.join(RESOURCE_ROOT, "smell_ai"))
        traditional_analyzer = TraditionalSmellAnalyzer(dpy_binary=dpy_binary)
        vuln_analyzer = BanditVulnerabilityAnalyzer() if vulnerabilities_enabled else None

        snap_ml = ml_analyzer.analyze_directory(repo_path, None)
        snap_traditional = traditional_analyzer.analyze_directory(repo_path, email_to_dev_id)
        snap_vulnerabilities = vuln_analyzer.analyze_directory(repo_path, email_to_dev_id) if vuln_analyzer else []

        ml_enriched = _attribute_instances_to_developers(
            snap_ml, repo_path, email_to_dev_id, base_dev_by_id
        )
        traditional_enriched = _attribute_instances_to_developers(
            snap_traditional, repo_path, email_to_dev_id, base_dev_by_id
        )
        vulnerabilities_enriched = _attribute_instances_to_developers(
            snap_vulnerabilities, repo_path, email_to_dev_id, base_dev_by_id
        )

        loc, nom = _compute_loc_nom_for_snapshot(repo_path)

        return {
            "ml_enriched": ml_enriched,
            "traditional_enriched": traditional_enriched,
            "vulnerabilities_enriched": vulnerabilities_enriched,
            "loc": loc,
            "nom": nom,
            "ml_status": ml_analyzer.last_status,
            "ml_error": ml_analyzer.last_error,
            "ml_stdout": (ml_analyzer.last_stdout or "")[:4000] or None,
            "ml_stderr": (ml_analyzer.last_stderr or "")[:4000] or None,
            "ml_call_graph_nodes": ml_analyzer.last_call_graph_nodes,
            "ml_call_graph_edges": ml_analyzer.last_call_graph_edges,
        }
    finally:
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path, ignore_errors=True)


def _attribute_instances_to_developers(
    instances: List[Any],
    repo_path: str,
    email_to_dev_id: Dict[str, str],
    known_dev_ids: Dict[str, Developer],
) -> List[Tuple[Any, Optional[datetime]]]:
    blame_cache: Dict[Tuple[str, int], Optional[Dict[str, object]]] = {}
    valid_ids = set(known_dev_ids.keys())
    enriched: List[Tuple[Any, Optional[datetime]]] = []

    for inst in instances:
        entities = [x for x in getattr(inst, "affected_entities", []) if isinstance(x, str)]
        file_path = getattr(inst, "file_path", None)
        line = getattr(inst, "line", None)
        line_no = int(line) if line else None
        intro_date: Optional[datetime] = None

        info = None
        if file_path and line_no:
            key = (str(file_path), line_no)
            info = blame_cache.get(key)
            if key not in blame_cache:
                info = _blame_line_info(repo_path, file_path, line_no)
                blame_cache[key] = info
            if info and isinstance(info, dict):
                intro_date = info.get("author_date")

        if not any(e in valid_ids for e in entities):
            email = info.get("author_email") if isinstance(info, dict) else None
            author_id = email_to_dev_id.get(str(email).lower()) if email else None
            if author_id:
                inst.affected_entities = [author_id]

        enriched.append((inst, intro_date))

    return enriched


def _sanitize_repo_slug(url: str) -> str:
    slug = (url or "").rstrip("/").split("/")[-1].replace(".git", "").strip()
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", slug).strip("-")
    return slug or f"repo-{uuid.uuid4().hex[:8]}"


def _resolve_dpy_binary() -> Optional[str]:
    def _matches_current_platform(path: str) -> bool:
        try:
            with open(path, "rb") as f:
                header = f.read(4)
        except OSError:
            return False

        if header.startswith(b"#!"):
            return True

        is_windows_bin = header.startswith(b"MZ")
        is_linux_bin = header.startswith(b"\x7fELF")
        is_macos_bin = header in {
            b"\xCF\xFA\xED\xFE",
            b"\xFE\xED\xFA\xCF",
            b"\xCA\xFE\xBA\xBE",
            b"\xBE\xBA\xFE\xCA",
            b"\xCA\xFE\xBA\xBF",
            b"\xBF\xBA\xFE\xCA",
        }

        if sys.platform.startswith("win"):
            return not (is_linux_bin or is_macos_bin)
        if sys.platform == "darwin":
            return not (is_linux_bin or is_windows_bin)
        return not (is_windows_bin or is_macos_bin)

    candidates: List[str] = []
    env_path = (os.environ.get("DPY_BINARY", "") or "").strip()
    if env_path:
        candidates.append(os.path.expanduser(env_path))

    folder_candidates: List[Tuple[str, ...]] = []
    if sys.platform.startswith("win"):
        folder_candidates.extend([
            ("DPy_WINDOWS", "DPy.exe"),
            ("DPy_WINDOWS", "DPy"),
        ])
    elif sys.platform == "darwin":
        folder_candidates.extend([
            ("DPy_MACOS", "DPy"),
            ("DPy_MACOS", "dpy"),
        ])
    else:
        folder_candidates.extend([
            ("DPy_LINUX", "DPy"),
            ("DPy_LINUX", "dpy"),
        ])

    # Also consider sibling platform folders as generic fallbacks when the
    # current platform-specific directory is missing.
    folder_candidates.extend([
        ("DPy_WINDOWS", "DPy.exe"),
        ("DPy_WINDOWS", "DPy"),
        ("DPy_MACOS", "DPy"),
        ("DPy_MACOS", "dpy"),
        ("DPy_LINUX", "DPy"),
        ("DPy_LINUX", "dpy"),
    ])
    for parts in folder_candidates:
        candidates.append(os.path.join(RESOURCE_ROOT, *parts))

    name_candidates = [
        "DPy",
        "dpy",
        "DPy-macos",
        "DPy-macos-arm64",
        "DPy-macos-x86_64",
        "DPy-darwin",
        "DPy-darwin-arm64",
        "DPy-darwin-x86_64",
        "DPy-linux",
        "DPy-linux-x86_64",
        "DPy-linux-amd64",
        "DPy.Linux.x86_64",
        "DPy.exe",
    ]
    for name in name_candidates:
        candidates.append(os.path.join(RESOURCE_ROOT, name))

    for cmd_name in ("DPy", "dpy"):
        path_in_path = shutil.which(cmd_name)
        if path_in_path:
            candidates.append(path_in_path)

    seen: set = set()
    for raw in candidates:
        p = os.path.abspath(raw)
        if p in seen:
            continue
        seen.add(p)
        if not os.path.isfile(p):
            continue
        if not _matches_current_platform(p):
            continue
        if os.name != "nt" and not os.access(p, os.X_OK):
            try:
                mode = os.stat(p).st_mode
                os.chmod(p, mode | 0o111)
            except Exception:
                pass
        if os.name == "nt" or os.access(p, os.X_OK):
            return p
    return None


def _allocate_repo_folder(repo_slug: str) -> str:
    base = PROJECTS_ROOT
    os.makedirs(base, exist_ok=True)
    candidate = os.path.join(base, repo_slug)
    if not os.path.exists(candidate):
        return candidate
    idx = 2
    while True:
        alt = os.path.join(base, f"{repo_slug}-{idx}")
        if not os.path.exists(alt):
            return alt
        idx += 1


def _looks_like_missing_repo_error(stderr_text: str) -> bool:
    txt = (stderr_text or "").lower()
    markers = [
        "repository not found",
        "not found",
        "does not exist",
        "could not find repository",
        "remote repository is empty",
        "fatal: repository",
    ]
    return any(m in txt for m in markers)


def _git_clone_with_timeout(url: str, dest_path: str) -> None:
    timeout_sec = int(os.environ.get("GIT_CLONE_TIMEOUT_SEC", "180"))
    cmd = ["git", "clone", "--", url, dest_path]
    try:
        res = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(timeout_sec, 10),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Clone timed out after {timeout_sec}s for '{url}'. "
            "Repository may be unavailable or too large."
        )
    except Exception as e:
        raise RuntimeError(f"Clone failed for '{url}': {e}")

    if res.returncode == 0:
        return

    stderr_text = (res.stderr or res.stdout or "").strip()
    if _looks_like_missing_repo_error(stderr_text):
        raise ValueError(
            f"Repository unavailable or removed: {url}. "
            f"Git said: {stderr_text[:400]}"
        )
    raise RuntimeError(
        f"Failed to clone '{url}' (exit {res.returncode}). "
        f"Git said: {stderr_text[:700]}"
    )


def _path_is_git_repository(path: str) -> bool:
    if not path:
        return False
    git_marker = os.path.join(path, ".git")
    return os.path.isdir(path) and os.path.exists(git_marker)


def _discover_git_repositories(root_path: str) -> List[str]:
    if not root_path:
        return []
    abs_root = os.path.abspath(root_path)
    if _path_is_git_repository(abs_root):
        return [abs_root]
    if not os.path.isdir(abs_root):
        return []

    skip_dirs = {
        ".venv", "venv", "__pycache__", "node_modules",
        ".mypy_cache", ".pytest_cache", ".ruff_cache",
    }
    discovered: List[str] = []
    seen: set = set()
    for current_root, dirnames, filenames in os.walk(abs_root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        if ".git" in dirnames or ".git" in filenames:
            repo_path = os.path.abspath(current_root)
            repo_key = os.path.normcase(os.path.normpath(repo_path))
            if repo_key not in seen:
                seen.add(repo_key)
                discovered.append(repo_path)
            dirnames[:] = []
    discovered.sort()
    return discovered


def _create_project_record(
    name: str,
    url: str = "",
    local_path: str = "",
    vulnerability_analysis_enabled: bool = False,
    expected_generation: Optional[int] = None,
) -> Project:
    if _is_generation_cancelled(expected_generation):
        raise AnalysisCancelled("Import cancelled by Delete All Projects.")
    project_id = str(uuid.uuid4())

    if local_path and os.path.isabs(local_path):
        final_path = local_path
        if not os.path.exists(final_path):
            raise ValueError(f"Local path does not exist: {final_path}")
        if not _path_is_git_repository(final_path):
            raise ValueError(
                f"Local path is not a git repository: {final_path}. "
                "Use a repository root, or use the import path scan to load all repositories inside a folder."
            )
    elif url:
        repo_slug = _sanitize_repo_slug(url)
        folder_name = local_path.strip("/") if local_path else repo_slug
        final_path = _allocate_repo_folder(folder_name)
        if not os.path.exists(final_path):
            _git_clone_with_timeout(url, final_path)
    else:
        raise ValueError("Provide either a Git URL or an absolute local path.")

    project = Project(
        id=project_id,
        name=name,
        url=url,
        local_path=final_path,
        vulnerability_analysis_enabled=bool(vulnerability_analysis_enabled),
        analysis_status="None",
    )
    if _is_generation_cancelled(expected_generation):
        # Prevent resurrecting projects while global cleanup is in progress.
        if url and os.path.exists(final_path):
            try:
                shutil.rmtree(final_path, ignore_errors=True)
            except Exception:
                pass
        raise AnalysisCancelled("Import cancelled by Delete All Projects.")
    with _PROJECTS_DB_LOCK:
        if _is_generation_cancelled(expected_generation):
            raise AnalysisCancelled("Import cancelled by Delete All Projects.")
        projects_db[project_id] = project
        save_projects(projects_db)
    return project


class BulkRepoItem(BaseModel):
    url: str
    name: Optional[str] = None
    local_path: Optional[str] = ""
    vulnerability_analysis_enabled: bool = False


class BulkCreateRequest(BaseModel):
    repositories: List[BulkRepoItem] = Field(default_factory=list)
    auto_analyze: bool = True


def _expand_bulk_repo_items(items: List[BulkRepoItem]) -> List[BulkRepoItem]:
    expanded: List[BulkRepoItem] = []
    for item in items or []:
        if not isinstance(item, BulkRepoItem):
            continue
        url = str(item.url or "").strip()
        local_path = str(item.local_path or "").strip()
        if url or not local_path or not os.path.isabs(local_path) or not os.path.exists(local_path):
            expanded.append(item)
            continue

        discovered = _discover_git_repositories(local_path)
        if not discovered:
            expanded.append(item)
            continue

        original_norm = os.path.normcase(os.path.normpath(os.path.abspath(local_path)))
        if len(discovered) == 1 and os.path.normcase(os.path.normpath(discovered[0])) == original_norm:
            expanded.append(
                BulkRepoItem(
                    url="",
                    name=item.name,
                    local_path=discovered[0],
                    vulnerability_analysis_enabled=bool(item.vulnerability_analysis_enabled),
                )
            )
            continue

        for repo_path in discovered:
            expanded.append(
                BulkRepoItem(
                    url="",
                    name=os.path.basename(repo_path.rstrip("\\/")) or None,
                    local_path=repo_path,
                    vulnerability_analysis_enabled=bool(item.vulnerability_analysis_enabled),
                )
            )
    return expanded


def _create_projects_from_items(
    items: List[BulkRepoItem],
    auto_analyze: bool,
    expected_generation: Optional[int] = None,
) -> Dict[str, Any]:
    if not items:
        raise HTTPException(status_code=400, detail="No repositories provided.")
    items = _expand_bulk_repo_items(items)
    if not items:
        raise HTTPException(status_code=400, detail="No repositories found in the provided paths.")

    def worker(idx: int, item: BulkRepoItem) -> Dict[str, Any]:
        if _is_generation_cancelled(expected_generation):
            return {
                "ok": False,
                "index": idx,
                "row": {"index": str(idx), "url": "", "name": "", "error": "Cancelled by Delete All Projects"},
            }
        url = (item.url or "").strip()
        local_path = (item.local_path or "").strip()
        name = (item.name or "").strip()

        if not name:
            if url:
                name = _sanitize_repo_slug(url)
            elif local_path:
                name = os.path.basename(local_path.rstrip("/")) or f"repo-{idx + 1}"
            else:
                name = f"repo-{idx + 1}"

        try:
            project = _create_project_record(
                name=name,
                url=url,
                local_path=local_path,
                vulnerability_analysis_enabled=bool(item.vulnerability_analysis_enabled),
                expected_generation=expected_generation,
            )

            if auto_analyze and not _is_generation_cancelled(expected_generation):
                with _PROJECTS_DB_LOCK:
                    if project.id in projects_db:
                        project.analysis_status = "Queued"
                        project.ml_detection_status = "Queued for analysis..."
                        _set_analysis_progress(project, 0.0, None, 0, 0)
                        save_projects(projects_db)
                _enqueue_analysis(project.id, generation=expected_generation)

            return {
                "ok": True,
                "index": idx,
                "row": {
                    "id": project.id,
                    "name": project.name,
                    "url": project.url,
                    "status": project.analysis_status,
                },
            }
        except AnalysisCancelled as e:
            return {
                "ok": False,
                "index": idx,
                "row": {"index": str(idx), "url": url, "name": name, "error": str(e)},
            }
        except ValueError as e:
            return {
                "ok": False,
                "index": idx,
                "row": {"index": str(idx), "url": url, "name": name, "error": str(e)},
            }
        except Exception as e:
            return {
                "ok": False,
                "index": idx,
                "row": {"index": str(idx), "url": url, "name": name, "error": str(e)},
            }

    workers = max(
        1,
        min(
            _read_parallelism_env("IMPORT_PARALLELISM", _adaptive_import_parallelism()),
            len(items),
        ),
    )
    results: List[Dict[str, Any]] = []
    if workers <= 1 or len(items) <= 1:
        for idx, item in enumerate(items):
            results.append(worker(idx, item))
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(worker, idx, item) for idx, item in enumerate(items)]
            for fut in as_completed(futs):
                results.append(fut.result())

    results.sort(key=lambda x: int(x.get("index", 0)))
    created = [r["row"] for r in results if r.get("ok")]
    errors = [r["row"] for r in results if not r.get("ok")]

    return {
        "requested": len(items),
        "auto_analyze": auto_analyze,
        "created": created,
        "errors": errors,
    }


def _import_items_background(
    items: List[BulkRepoItem],
    auto_analyze: bool,
    expected_generation: Optional[int] = None,
) -> None:
    try:
        _create_projects_from_items(items, auto_analyze, expected_generation=expected_generation)
    except Exception:
        print("Background CSV import failed:")
        print(traceback.format_exc())


@app.post("/projects", response_model=Project)
async def create_project(name: str, url: str = "", local_path: str = "", vulnerability_analysis_enabled: bool = False):
    try:
        return _create_project_record(
            name=name,
            url=url,
            local_path=local_path,
            vulnerability_analysis_enabled=vulnerability_analysis_enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create project '{name}': {str(e)}")


def _build_demo_conflict_project(name: str = "Demo Conflict Playground") -> Project:
    now = datetime.now()
    start = now - timedelta(days=30)
    end = now
    project_id = str(uuid.uuid4())

    dev_se = Developer(
        id="alice_se@example.com",
        aliases=["alice-se"],
        emails=["alice_se@example.com"],
        classification="Software Engineer",
        commits_count=14,
        bug_fix_commits_count=3,
        bug_introduced_count=1,
        files_touched_count=18,
        lines_added=620,
        lines_deleted=210,
        code_churn=830,
    )
    dev_ml = Developer(
        id="bob_ml@example.com",
        aliases=["bob-ml"],
        emails=["bob_ml@example.com"],
        classification="AI/ML Engineer",
        commits_count=11,
        bug_fix_commits_count=2,
        bug_introduced_count=2,
        files_touched_count=15,
        lines_added=510,
        lines_deleted=260,
        code_churn=770,
    )
    dev_hybrid = Developer(
        id="carla_hybrid@example.com",
        aliases=["carla-hybrid"],
        emails=["carla_hybrid@example.com"],
        classification="Hybrid",
        commits_count=17,
        bug_fix_commits_count=4,
        bug_introduced_count=1,
        files_touched_count=22,
        lines_added=890,
        lines_deleted=340,
        code_churn=1230,
    )
    developers = [dev_se, dev_ml, dev_hybrid]

    edges = [
        {"from": 0, "to": 1, "weight": 4},
        {"from": 0, "to": 2, "weight": 3},
        {"from": 1, "to": 2, "weight": 5},
    ]

    metrics = ProjectMetrics(
        project_id=project_id,
        time_window="demo-window",
        loc=18240,
        nom=1290,
        community_smells_count={"lone_wolf": 1},
        ml_smells_count={"data_leakage": 2},
        traditional_smells_count={"LongMethod": 3},
        vulnerabilities_count={"B101": 1},
        vulnerabilities_severity_count={"HIGH": 1},
        abandoned_developers_count=0,
        abandoned_developers_ids=[],
    )
    window = ProjectTimeWindow(
        id="demo-window",
        label="Demo Window",
        start_date=start,
        end_date=end,
        developers=developers,
        metrics=metrics,
        collaboration_edges=edges,
    )

    trace_a = TraceabilityLink(
        source_id="issue:42:comment:1",
        label="Issue #42 comment disagreement",
        url="https://github.com/example/demo/issues/42",
        source_type="issue_comment",
        is_open=True,
    )
    trace_b = TraceabilityLink(
        source_id="pr:77:review:2",
        label="PR #77 changes requested",
        url="https://github.com/example/demo/pull/77",
        source_type="review",
        is_open=False,
    )
    trace_c = TraceabilityLink(
        source_id="pr:81:comment:5",
        label="PR #81 contested architecture choice",
        url="https://github.com/example/demo/pull/81",
        source_type="pr_comment",
        is_open=True,
    )

    topic_modeling = TopicModelingResult(
        status="Completed (Demo)",
        model="demo-synthetic",
        judge_model="demo-synthetic-judge",
        generated_at=now,
        source_count=36,
        discussion_source_count=28,
        llm_run_count=1,
        judged=True,
        source_breakdown={
            "issue_comment": 10,
            "pr_comment": 12,
            "review": 6,
            "commit_message": 8,
        },
        taxonomy_notes=[
            "This is a synthetic dataset created to validate graph rendering of conflicts and topics.",
        ],
        roles=[
            RoleTopicTree(
                role="Software Engineer",
                documents_count=12,
                summary="SE discussions focus on delivery risk and refactoring tradeoffs.",
                topics=[
                    TopicNode(
                        name="Release Gatekeeping",
                        summary="SE contributors debated stability thresholds before release.",
                        evidence_count=3,
                        subtopics=[
                            TopicSubtopic(
                                name="Rollback Policy",
                                summary="Different opinions on rollback triggers.",
                                evidence_count=3,
                                trace_links=[trace_a, trace_b],
                            )
                        ],
                        trace_links=[trace_a],
                    )
                ],
            ),
            RoleTopicTree(
                role="AI/ML Engineer",
                documents_count=11,
                summary="ML discussions concentrate on model quality and data constraints.",
                topics=[
                    TopicNode(
                        name="Data Validation",
                        summary="ML contributors pushed for stricter validation checks.",
                        evidence_count=2,
                        trace_links=[trace_a, trace_c],
                    )
                ],
            ),
            RoleTopicTree(
                role="Hybrid",
                documents_count=13,
                summary="Hybrid contributors bridge architecture and model concerns.",
                topics=[
                    TopicNode(
                        name="Pipeline Ownership",
                        summary="Hybrid developers debated ownership of feature pipelines.",
                        evidence_count=2,
                        trace_links=[trace_c],
                    )
                ],
            ),
        ],
        developers=[
            DeveloperTopicProfile(
                developer_id=dev_se.id,
                role="Software Engineer",
                documents_count=10,
                summary="Frequent participation in release and code quality debates.",
                topics=[
                    TopicNode(
                        name="Release Gatekeeping",
                        summary="Argued for strict merge criteria.",
                        evidence_count=2,
                        trace_links=[trace_b],
                    )
                ],
                trace_links=[trace_b],
            ),
            DeveloperTopicProfile(
                developer_id=dev_ml.id,
                role="AI/ML Engineer",
                documents_count=9,
                summary="Focused on model reliability and data integrity.",
                topics=[
                    TopicNode(
                        name="Data Validation",
                        summary="Insisted on stronger validation before deploy.",
                        evidence_count=2,
                        trace_links=[trace_a],
                    )
                ],
                trace_links=[trace_a],
            ),
            DeveloperTopicProfile(
                developer_id=dev_hybrid.id,
                role="Hybrid",
                documents_count=11,
                summary="Bridged platform and ML concerns during design reviews.",
                topics=[
                    TopicNode(
                        name="Pipeline Ownership",
                        summary="Challenged unclear ownership boundaries.",
                        evidence_count=2,
                        trace_links=[trace_c],
                    )
                ],
                trace_links=[trace_c],
            ),
        ],
        conflicts=[
            DeveloperConflictRecord(
                conflict_title="Model rollback criteria",
                developer_id=dev_se.id,
                developer_role="Software Engineer",
                counterpart_id=dev_ml.id,
                counterpart_role="AI/ML Engineer",
                participant_ids=[dev_se.id, dev_ml.id],
                participant_roles=["Software Engineer", "AI/ML Engineer"],
                role_combination="Software Engineer x AI/ML Engineer",
                status="open",
                summary="Disagreement on rollback thresholds for model degradation.",
                resolution_summary="Not yet resolved; discussion remains active in issue thread.",
                evidence_count=3,
                open_conflict=True,
                primary_link=trace_a,
                source_links=[trace_a, trace_b],
            ),
            DeveloperConflictRecord(
                conflict_title="Code ownership boundaries",
                developer_id=dev_se.id,
                developer_role="Software Engineer",
                counterpart_id=dev_hybrid.id,
                counterpart_role="Hybrid",
                participant_ids=[dev_se.id, dev_hybrid.id],
                participant_roles=["Software Engineer", "Hybrid"],
                role_combination="Software Engineer x Hybrid",
                status="resolved",
                summary="Debate on who should own integration-layer modules.",
                resolution_summary="Resolved by defining ownership in PR template and CODEOWNERS.",
                evidence_count=2,
                open_conflict=False,
                primary_link=trace_b,
                source_links=[trace_b],
            ),
            DeveloperConflictRecord(
                conflict_title="Hybrid architecture dispute",
                developer_id=dev_hybrid.id,
                developer_role="Hybrid",
                counterpart_id=dev_hybrid.id,
                counterpart_role="Hybrid",
                participant_ids=[dev_hybrid.id],
                participant_roles=["Hybrid"],
                role_combination="Hybrid",
                status="open",
                summary="Conflicting proposals among hybrid maintainers on pipeline design.",
                resolution_summary="Pending decision in open PR discussion.",
                evidence_count=2,
                open_conflict=True,
                primary_link=trace_c,
                source_links=[trace_c],
            ),
        ],
        potential_conflict_threads=[
            PotentialConflictThread(
                thread_id="issue:99",
                thread_label="Issue #99 deployment regression",
                thread_url="https://github.com/example/demo/issues/99",
                source_type="issue",
                is_open=True,
                participant_ids=[dev_se.id, dev_ml.id, dev_hybrid.id],
                participant_roles=["Software Engineer", "AI/ML Engineer", "Hybrid"],
                matched_signals=["blocked", "changes_requested", "concern"],
                summary="Heuristic candidate thread with repeated blocking language.",
                source_links=[trace_a, trace_c],
            )
        ],
    )

    return Project(
        id=project_id,
        name=name,
        url="demo://conflict-playground",
        local_path=PROJECT_ROOT,
        last_analyzed=now,
        analysis_status="Completed",
        analysis_progress_pct=100.0,
        analysis_eta_seconds=0,
        analysis_window_index=1,
        analysis_window_total=1,
        last_analysis_duration_seconds=1.0,
        last_analysis_window_count=1,
        ml_detection_status="Completed (Demo)",
        developers=developers,
        metrics=[metrics],
        collaboration_edges=edges,
        time_windows=[window],
        active_time_window_id=window.id,
        topic_modeling=topic_modeling,
    )


@app.post("/projects/demo/conflicts", response_model=Project)
async def create_demo_conflict_project(name: str = "Demo Conflict Playground", replace_existing: bool = True):
    demo_url = "demo://conflict-playground"
    with _PROJECTS_DB_LOCK:
        if replace_existing:
            existing_ids = [pid for pid, project in projects_db.items() if str(project.url or "").strip() == demo_url]
            for project_id in existing_ids:
                projects_db.pop(project_id, None)
                _delete_topic_documents(project_id)
        demo_project = _build_demo_conflict_project(name=name)
        projects_db[demo_project.id] = demo_project
        _save_topic_documents(
            demo_project.id,
            [
                {
                    "project_id": demo_project.id,
                    "project_name": demo_project.name,
                    "time_window_id": "demo-window",
                    "time_window_label": "Demo Window",
                    "source_id": "issue:42:comment:1",
                    "source_label": "Issue #42 comment disagreement",
                    "source_url": "https://github.com/example/demo/issues/42",
                    "source_type": "issue_comment",
                    "is_open": True,
                    "thread_id": "issue:42",
                    "thread_label": "Issue #42 rollback criteria",
                    "thread_url": "https://github.com/example/demo/issues/42",
                    "thread_is_open": True,
                    "developer_id": "alice_se@example.com",
                    "role": "Software Engineer",
                    "text": "We should block release until rollback criteria are explicit.",
                    "timestamp": datetime.now().isoformat(),
                }
            ],
        )
        save_projects(projects_db)
    _invalidate_global_topics_cache()
    return demo_project


@app.post("/projects/bulk")
async def create_projects_bulk(
    payload: BulkCreateRequest,
    background_tasks: BackgroundTasks,
    async_import: bool = False,
):
    generation = _get_workflow_generation()
    expanded_items = _expand_bulk_repo_items(payload.repositories)
    if async_import:
        background_tasks.add_task(_import_items_background, expanded_items, payload.auto_analyze, generation)
        return {
            "mode": "async",
            "message": "Bulk import started in background",
            "requested": len(expanded_items or []),
            "auto_analyze": payload.auto_analyze,
        }
    return _create_projects_from_items(
        expanded_items,
        payload.auto_analyze,
        expected_generation=generation,
    )


@app.post("/projects/import/csv")
async def import_projects_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    auto_analyze: bool = Form(True),
    vulnerability_analysis_enabled: bool = Form(False),
    async_import: bool = Form(True),
):
    filename = (file.filename or "").lower()
    if not filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file.")

    try:
        raw = await file.read()
        text = raw.decode("utf-8-sig", errors="ignore")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read CSV file: {e}")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV file has no header.")

    lowered = {str(h).strip().lower(): h for h in reader.fieldnames if h}

    def get_col(*names: str) -> Optional[str]:
        for n in names:
            if n in lowered:
                return lowered[n]
        return None

    url_col = get_col("url", "repo_url", "repository_url", "git_url")
    name_col = get_col("name", "project_name")
    local_path_col = get_col("local_path", "path", "repo_path")

    if not url_col and not local_path_col:
        raise HTTPException(
            status_code=400,
            detail="CSV must contain at least one column among: url/repo_url/repository_url/git_url or local_path/path/repo_path.",
        )

    items: List[BulkRepoItem] = []
    for row in reader:
        if not isinstance(row, dict):
            continue
        url = str(row.get(url_col, "") or "").strip() if url_col else ""
        name = str(row.get(name_col, "") or "").strip() if name_col else ""
        local_path = str(row.get(local_path_col, "") or "").strip() if local_path_col else ""
        if not url and not local_path:
            continue
        items.append(
            BulkRepoItem(
                url=url,
                name=name or None,
                local_path=local_path,
                vulnerability_analysis_enabled=bool(vulnerability_analysis_enabled),
            )
        )

    if not items:
        raise HTTPException(status_code=400, detail="No valid rows found in CSV.")

    items = _expand_bulk_repo_items(items)
    generation = _get_workflow_generation()
    if async_import:
        background_tasks.add_task(_import_items_background, items, auto_analyze, generation)
        return {
            "mode": "async",
            "message": "CSV import started in background",
            "requested": len(items),
            "auto_analyze": auto_analyze,
        }

    return _create_projects_from_items(items, auto_analyze, expected_generation=generation)


@app.get("/settings/llm", response_model=LLMSettingsResponse)
async def get_llm_settings():
    return _build_llm_settings_response()


@app.put("/settings/llm", response_model=LLMSettingsResponse)
async def update_llm_settings(payload: LLMSettingsUpdateRequest):
    current = _load_llm_settings_raw()

    if payload.clear_api_key:
        current["api_key"] = ""
    elif payload.api_key is not None and str(payload.api_key).strip():
        current["api_key"] = str(payload.api_key).strip()

    if payload.clear_github_token:
        current["github_token"] = ""
    elif payload.github_token is not None and str(payload.github_token).strip():
        current["github_token"] = str(payload.github_token).strip()

    if payload.model is not None:
        current["model"] = str(payload.model).strip() or "gpt-5-mini"
    if payload.llm_runs is not None:
        try:
            current["llm_runs"] = max(1, min(7, int(payload.llm_runs)))
        except Exception:
            current["llm_runs"] = 1
    if payload.organization is not None:
        current["organization"] = str(payload.organization).strip()
    if payload.project is not None:
        current["project"] = str(payload.project).strip()
    if payload.endpoint is not None:
        current["endpoint"] = str(payload.endpoint).strip() or "https://api.openai.com/v1/chat/completions"

    _save_llm_settings_raw(current)
    _invalidate_global_topics_cache()
    return _build_llm_settings_response()


@app.get("/projects", response_model=List[Project])
async def list_projects():
    with _PROJECTS_DB_LOCK:
        return list(projects_db.values())


@app.delete("/projects")
async def delete_all_projects():
    _bump_workflow_generation()
    with _RUNNING_ANALYSES_LOCK:
        for fut in list(_ANALYSIS_FUTURES.values()):
            fut.cancel()
        _ANALYSIS_FUTURES.clear()
        _RUNNING_ANALYSES.clear()

    with _PROJECTS_DB_LOCK:
        unique_paths = {p.local_path for p in projects_db.values() if p.local_path}
    deleted_folders = 0

    managed_root = os.path.normpath(PROJECTS_ROOT)
    for local_path in unique_paths:
        try:
            if not os.path.exists(local_path):
                continue
            local_norm = os.path.normpath(local_path)
            if os.path.commonpath([managed_root, local_norm]) != managed_root:
                continue
            shutil.rmtree(local_path)
            deleted_folders += 1
        except Exception as e:
            print(f"Failed to remove {local_path}: {e}")

    with _PROJECTS_DB_LOCK:
        deleted_projects = len(projects_db)
        topic_project_ids = list(projects_db.keys())
        projects_db.clear()
        save_projects(projects_db)
    for project_id in topic_project_ids:
        _delete_topic_documents(project_id)
    _invalidate_global_topics_cache()
    return {
        "message": "All projects deleted successfully",
        "projects_deleted": deleted_projects,
        "folders_deleted": deleted_folders,
    }


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    with _PROJECTS_DB_LOCK:
        if project_id not in projects_db:
            raise HTTPException(status_code=404, detail="Project not found")

        project = projects_db[project_id]
        used_by_other_projects = any(
            (p.id != project_id and p.local_path == project.local_path)
            for p in projects_db.values()
        )
    managed_root = os.path.normpath(PROJECTS_ROOT)
    local_norm = os.path.normpath(project.local_path or "")
    should_delete_managed = False
    if local_norm and os.path.exists(local_norm):
        try:
            should_delete_managed = os.path.commonpath([managed_root, local_norm]) == managed_root
        except Exception:
            should_delete_managed = False

    if should_delete_managed and not used_by_other_projects:
        try:
            shutil.rmtree(project.local_path)
        except Exception as e:
            print(f"Failed to remove {project.local_path}: {e}")

    with _PROJECTS_DB_LOCK:
        if project_id in projects_db:
            del projects_db[project_id]
            save_projects(projects_db)
    _delete_topic_documents(project_id)
    _invalidate_global_topics_cache()
    return {"message": "Project deleted successfully"}


@app.post("/projects/{project_id}/analyze")
async def start_analysis(project_id: str):
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")

    project = projects_db[project_id]
    project.analysis_status = "Queued"
    project.ml_detection_status = "Queued for analysis..."
    _set_analysis_progress(project, 0.0, None, 0, 0)
    # Keep previous windows visible while the new analysis is running.
    save_projects(projects_db)

    queued = _enqueue_analysis(project_id)
    if queued:
        return {"message": "Analysis queued", "project_id": project_id}
    return {"message": "Analysis already running or queued", "project_id": project_id}


@app.post("/projects/analyze-all")
async def start_analysis_all(force_reanalyze: bool = False):
    queued_count = 0
    skipped_completed = 0
    already_running_or_queued = 0
    touched = False

    for project in projects_db.values():
        has_existing_results = bool(project.last_analyzed) or bool(project.time_windows) or bool(project.developers) or bool(project.metrics)
        if has_existing_results and not force_reanalyze:
            skipped_completed += 1
            continue

        if project.analysis_status in {"Running", "Queued", "Queued for automatic resume"}:
            already_running_or_queued += 1
            continue

        project.analysis_status = "Queued"
        project.ml_detection_status = "Queued for analysis..."
        _set_analysis_progress(project, 0.0, None, 0, 0)
        if _enqueue_analysis(project.id):
            queued_count += 1
            touched = True
        else:
            already_running_or_queued += 1

    if touched:
        save_projects(projects_db)

    return {
        "message": "Batch analysis scheduling completed",
        "queued": queued_count,
        "skipped_completed": skipped_completed,
        "already_running_or_queued": already_running_or_queued,
        "analysis_parallelism": _ANALYSIS_MAX_WORKERS,
    }


def run_full_analysis(project_id: str, expected_generation: Optional[int] = None):
    if _is_generation_cancelled(expected_generation):
        return
    project = projects_db.get(project_id)
    if not project:
        # Project may have been deleted before background task starts.
        return
    history_repo_path: Optional[str] = None
    analysis_started_at = datetime.now()
    topic_executor: Optional[ThreadPoolExecutor] = None
    topic_future: Optional[Future] = None
    analysis_progress_save_interval_sec = max(2.0, float(os.environ.get("ANALYSIS_PROGRESS_SAVE_INTERVAL_SEC", "12")))
    last_analysis_progress_save_at = datetime.min

    try:
        if _is_generation_cancelled(expected_generation):
            raise AnalysisCancelled("Analysis cancelled by Delete All Projects.")
        _set_analysis_progress(project, 2.0, None, 0, 0)
        _ensure_project_repo_available(project)

        project.ml_detection_status = "Pending"
        project.ml_detection_error = None
        project.ml_detection_stdout = None
        project.ml_detection_stderr = None
        project.ml_call_graph_nodes = []
        project.ml_call_graph_edges = []
        save_projects(projects_db)

        miner = RepositoryMiner(project.local_path)
        commits = miner.list_commits()
        all_developers = miner.get_developers()

        _set_analysis_progress(project, 8.0, None, 0, 0)
        project.ml_detection_status = "Resolving developer profiles..."
        save_projects(projects_db)
        GitHubGenderResolver(project.url).annotate_developers(all_developers)

        base_dev_by_id: Dict[str, Developer] = {d.id: d for d in all_developers}
        email_to_dev_id = _build_email_to_dev_id(all_developers)

        _set_analysis_progress(project, 12.0, None, 0, 0)
        base_window_months = 1
        project.ml_detection_status = "Running historical monthly analysis..."
        save_projects(projects_db)

        dpy_binary = _resolve_dpy_binary()
        traditional_analyzer = TraditionalSmellAnalyzer(dpy_binary=dpy_binary)
        if not dpy_binary:
            print(
                "DPy binary not found/executable. "
                "Set DPY_BINARY to a binary compatible with your current OS "
                "or place it in RESOURCE_ROOT."
            )
        vulnerabilities_enabled = _is_vulnerability_analysis_enabled(project)
        vuln_analyzer = BanditVulnerabilityAnalyzer() if vulnerabilities_enabled else None
        ml_analyzer = MLSmellAnalyzer(os.path.join(RESOURCE_ROOT, "smell_ai"))
        sentiment_analyzer = DeveloperSentimentAnalyzer(os.path.join(RESOURCE_ROOT, "SE_Emotion_PTM-3589"))

        project.ml_detection_status = "Preparing developer sentiment model..."
        save_projects(projects_db)
        sentiment_ready = sentiment_analyzer.ensure_model_trained()
        if not sentiment_ready and sentiment_analyzer.last_error:
            print(f"Developer sentiment disabled: {sentiment_analyzer.last_error}")

        windows = _build_time_windows(commits, months_per_window=base_window_months)
        total_windows = len(windows)
        _set_analysis_progress(project, 18.0, _estimate_window_eta_seconds(project, datetime.now(), 0, total_windows), 0, total_windows)
        save_projects(projects_db)
        commits_sorted_asc = sorted(commits, key=lambda c: c.date)
        github_http_cache: Dict[str, Any] = {}
        login_to_dev_id = _build_login_to_dev_id_map(all_developers)
        login_to_dev_id = _augment_login_to_dev_id_map_with_github_contributors(
            project.url,
            all_developers,
            login_to_dev_id,
            http_cache=github_http_cache,
        )
        repo_web_base = _github_repo_web_base(project.url)

        project_start = windows[0]["start"] if windows else datetime.now()
        project_end = windows[-1]["end_exclusive"] if windows else _add_months(project_start, base_window_months)
        project.ml_detection_status = "Collecting PR/Issue communication..."
        save_projects(projects_db)
        gh_interactions_all, gh_text_signals_all = _fetch_github_issue_pr_data(
            project.url,
            project_start,
            project_end,
            login_to_dev_id,
            http_cache=github_http_cache,
        )

        gh_interactions_all.sort(key=lambda x: x[2])
        gh_text_signals_all.sort(key=lambda x: x.get("timestamp") or datetime.min)

        window_commits_list: List[List[Commit]] = []
        window_gh_interactions_list: List[List[Tuple[str, str, datetime]]] = []
        window_gh_text_docs_list: List[List[Dict[str, Any]]] = []
        window_activity_ids: List[set] = []
        all_known_dev_ids: set = {d.id for d in all_developers if d.id}

        commit_cursor = 0
        interaction_cursor = 0
        signal_cursor = 0
        for w in windows:
            end_exclusive = w["end_exclusive"]

            commit_start = commit_cursor
            while commit_cursor < len(commits_sorted_asc) and commits_sorted_asc[commit_cursor].date < end_exclusive:
                commit_cursor += 1
            snapshot_commit = commits_sorted_asc[commit_cursor - 1] if commit_cursor > 0 else None
            w["snapshot_commit_hash"] = snapshot_commit.hash if snapshot_commit else None
            window_commits = commits_sorted_asc[commit_start:commit_cursor]
            window_commits_list.append(window_commits)

            interaction_start = interaction_cursor
            while interaction_cursor < len(gh_interactions_all) and gh_interactions_all[interaction_cursor][2] < end_exclusive:
                interaction_cursor += 1
            window_interactions = gh_interactions_all[interaction_start:interaction_cursor]
            window_gh_interactions_list.append(window_interactions)

            signal_start = signal_cursor
            while signal_cursor < len(gh_text_signals_all) and gh_text_signals_all[signal_cursor].get("timestamp") < end_exclusive:
                signal_cursor += 1
            window_text_docs = gh_text_signals_all[signal_start:signal_cursor]
            window_gh_text_docs_list.append(window_text_docs)

            commit_authors = {c.author_id for c in window_commits if c.author_id}
            comm_participants = {
                actor_id
                for (src, dst, _) in window_interactions
                for actor_id in (src, dst)
                if actor_id
            }
            active_ids = set(commit_authors) | set(comm_participants)
            window_activity_ids.append(active_ids)
            all_known_dev_ids.update(active_ids)

        last_active_window_idx: Dict[str, int] = {}
        for idx, active_ids in enumerate(window_activity_ids):
            for dev_id in active_ids:
                last_active_window_idx[dev_id] = idx

        snapshots: List[ProjectTimeWindow] = []
        classifier = DeveloperClassifier()
        rszz = RSZZAnalyzer(project.local_path)
        snapshot_cache: Dict[str, Dict[str, Any]] = {}
        prev_table3_state: Optional[Dict[str, set]] = None
        windows_started_at = datetime.now()
        latest_commit_by_dev: Dict[str, Commit] = {}
        interaction_documents: List[Dict[str, Any]] = []
        topic_analyzer = RoleTopicModelingAnalyzer(config=_effective_llm_config())
        topic_prepared_accumulator = topic_analyzer.prepare_documents_incremental()
        checkpoint_partial_results = project.last_analyzed is None

        def _save_analysis_progress_state(force: bool = False) -> None:
            nonlocal last_analysis_progress_save_at
            now = datetime.now()
            if not force and (now - last_analysis_progress_save_at).total_seconds() < analysis_progress_save_interval_sec:
                return
            save_projects(projects_db)
            last_analysis_progress_save_at = now

        def _register_interaction_document(doc: Optional[Dict[str, Any]]) -> None:
            if not doc:
                return
            interaction_documents.append(doc)
            topic_analyzer.add_document_to_prepared(topic_prepared_accumulator, doc)

        def _ensure_topic_analysis_started() -> None:
            nonlocal topic_executor, topic_future
            if topic_future is not None:
                return
            prepared_documents = topic_analyzer.finalize_prepared_documents(topic_prepared_accumulator)
            topic_executor = ThreadPoolExecutor(max_workers=1)
            topic_future = topic_executor.submit(
                topic_analyzer.analyze_prepared_documents,
                prepared_documents,
                project.name,
            )

        # R-SZZ is expensive: compute bug-inducing commits once, then assign each
        # event to its corresponding historical window.
        all_bic_hashes = rszz.identify_bug_inducing_commits(commits_sorted_asc)
        commit_by_hash = {c.hash: c for c in commits_sorted_asc}
        bic_events: List[Tuple[datetime, str]] = []
        for h in all_bic_hashes:
            c = commit_by_hash.get(h)
            if c and c.author_id:
                bic_events.append((c.date, c.author_id))
        bic_events.sort(key=lambda x: x[0])
        bic_cursor = 0

        # Phase 1: Parallel Bulk Analysis of Snapshots
        unique_hashes = sorted(list({str(w.get("snapshot_commit_hash")) for w in windows if w.get("snapshot_commit_hash")}))
        to_analyze = [h for h in unique_hashes if h not in snapshot_cache]
        
        if to_analyze:
            project.ml_detection_status = f"Parallel Analysis: {len(to_analyze)} snapshots..."
            _save_analysis_progress_state(force=True)
            
            max_workers = int(os.environ.get("SMELLHUB_MAX_WORKERS", str(max(1, (os.cpu_count() or 2) // 2))))
            worker_args = [
                (h, project.local_path, dpy_binary, os.path.join(RESOURCE_ROOT, "smell_ai"), vulnerabilities_enabled, email_to_dev_id, base_dev_by_id)
                for h in to_analyze
            ]
            
            with ProcessPoolExecutor(max_workers=max_workers) as pool:
                futures = [pool.submit(_analyze_snapshot_worker, arg) for arg in worker_args]
                completed_count = 0
                for fut in as_completed(futures):
                    if _is_generation_cancelled(expected_generation):
                        raise AnalysisCancelled("Analysis cancelled.")
                    
                    try:
                        res = fut.result()
                    except Exception as e:
                        res = {"error": str(e)}

                    if "error" in res:
                        print(f"Worker process error: {res['error']}")
                    else:
                        target_hash = res["snapshot_hash"]
                        snapshot_cache[target_hash] = res
                    
                    completed_count += 1
                    project.ml_detection_status = f"Parallel Analysis: {completed_count}/{len(to_analyze)} snapshots..."
                    _set_analysis_progress(
                        project,
                        20.0 + (50.0 * (float(completed_count) / float(len(to_analyze)))),
                        None,
                        completed_count,
                        len(to_analyze)
                    )
                    _save_analysis_progress_state()

        # Phase 2: Sequential aggregation
        for idx, w in enumerate(windows):
            if _is_generation_cancelled(expected_generation):
                raise AnalysisCancelled("Analysis cancelled by Delete All Projects.")
            start = w["start"]
            end_exclusive = w["end_exclusive"]
            is_latest_window = idx == (len(windows) - 1)
            snapshot_hash = str(w.get("snapshot_commit_hash") or "")
            window_commits = window_commits_list[idx]
            window_gh_interactions = window_gh_interactions_list[idx]
            window_gh_text_docs = window_gh_text_docs_list[idx]
            window_latest_commit_by_dev: Dict[str, Commit] = {}
            for c in window_commits:
                if not c.author_id:
                    continue
                prev_commit = window_latest_commit_by_dev.get(c.author_id)
                if prev_commit is None or c.date > prev_commit.date:
                    window_latest_commit_by_dev[c.author_id] = c
            latest_commit_by_dev.update(window_latest_commit_by_dev)
            
            snapshot_result: Dict[str, Any]
            if snapshot_hash:
                cached = snapshot_cache.get(snapshot_hash)
                if cached is None:
                    snapshot_result = {
                        "ml_enriched": [], "traditional_enriched": [], "vulnerabilities_enriched": [],
                        "loc": 0, "nom": 0, "ml_status": "Parallel Failure", "ml_error": None,
                        "ml_stdout": None, "ml_stderr": None, "ml_call_graph_nodes": [], "ml_call_graph_edges": [],
                    }
                else:
                    snapshot_result = cached
            else:
                snapshot_result = {
                    "ml_enriched": [], "traditional_enriched": [], "vulnerabilities_enriched": [],
                    "loc": 0, "nom": 0, "ml_status": "No commits", "ml_error": None,
                    "ml_stdout": None, "ml_stderr": None, "ml_call_graph_nodes": [], "ml_call_graph_edges": [],
                }

            if is_latest_window:
                project.ml_detection_status = snapshot_result["ml_status"] or "Completed"
                project.ml_detection_error = snapshot_result["ml_error"]
                project.ml_detection_stdout = snapshot_result["ml_stdout"]
                project.ml_detection_stderr = snapshot_result["ml_stderr"]
                project.ml_call_graph_nodes = snapshot_result["ml_call_graph_nodes"] or []
                project.ml_call_graph_edges = snapshot_result["ml_call_graph_edges"] or []

            window_ml = [
                inst for (inst, intro_date) in snapshot_result["ml_enriched"]
                if (intro_date is not None and start <= intro_date < end_exclusive)
            ]
            window_traditional = [
                inst for (inst, intro_date) in snapshot_result["traditional_enriched"]
                if (intro_date is not None and start <= intro_date < end_exclusive)
            ]
            window_vulnerabilities = [
                inst for (inst, intro_date) in snapshot_result["vulnerabilities_enriched"]
                if (intro_date is not None and start <= intro_date < end_exclusive)
            ]

            window_dev_ids = {c.author_id for c in window_commits}
            for s in window_ml:
                window_dev_ids.update([x for x in s.affected_entities if isinstance(x, str) and x in base_dev_by_id])
            for s in window_traditional:
                window_dev_ids.update([x for x in s.affected_entities if isinstance(x, str) and x in base_dev_by_id])
            for v in window_vulnerabilities:
                window_dev_ids.update([x for x in v.affected_entities if isinstance(x, str) and x in base_dev_by_id])

            window_developers: List[Developer] = []
            for dev_id in window_dev_ids:
                base = base_dev_by_id.get(dev_id)
                if base:
                    window_developers.append(_clone_developer_identity(base))
                else:
                    window_developers.append(Developer(id=dev_id, aliases=[], emails=[]))

            window_bug_counts: Dict[str, int] = {}
            while bic_cursor < len(bic_events) and bic_events[bic_cursor][0] < end_exclusive:
                _, author_id = bic_events[bic_cursor]
                window_bug_counts[author_id] = window_bug_counts.get(author_id, 0) + 1
                bic_cursor += 1

            window_gh_text_by_dev: Dict[str, List[str]] = {}
            for signal in window_gh_text_docs:
                dev_id = str(signal.get("developer_id") or "").strip()
                txt = str(signal.get("text") or "").strip()
                if dev_id and txt:
                    window_gh_text_by_dev.setdefault(dev_id, []).append(txt)

            classifier.classify_developers(
                window_developers,
                window_commits,
                repo_root=history_repo_path,
                gh_text_by_dev=window_gh_text_by_dev,
            )
            _fill_developer_stats(window_developers, window_commits, window_bug_counts)
            if sentiment_ready:
                sentiment_analyzer.analyze_developers(window_developers, window_commits)

            nb = NetworkBuilder()
            nb.build_collaboration_network(window_commits)
            if window_gh_interactions:
                nb.communication_source = "github_pr_issue"
                nb.build_communication_network(window_gh_interactions)
            else:
                nb.communication_source = "commit_same_day_proxy"
                nb.build_communication_network(_build_proxy_communication_interactions(window_commits))

            c_analyzer = CommunitySmellAnalyzer(nb)
            community_smells = c_analyzer.detect_all()
            table3_metrics, prev_table3_state = _compute_table3_metrics(
                commits=window_commits,
                nb=nb,
                community_smells=community_smells,
                prev_state=prev_table3_state,
            )

            for dev in window_developers:
                dev.community_smells = []
                dev.ml_smells = []
                dev.ml_smell_details = []
                dev.traditional_smells = []
                dev.traditional_smell_details = []
                dev.vulnerabilities = []
                dev.vulnerability_details = []

            dev_by_id = {d.id: d for d in window_developers}

            for c in window_commits:
                dev = dev_by_id.get(c.author_id)
                if not dev or not c.message:
                    continue
                doc = _build_interaction_document(
                    project=project,
                    window_meta=w,
                    source_type="commit_message",
                    developer_id=c.author_id,
                    role=dev.classification,
                    text=c.message,
                    timestamp=c.date,
                    source_id=f"commit:{c.hash}",
                    source_label=f"Commit {str(c.hash or '')[:7]}",
                    source_url=f"{repo_web_base}/commit/{c.hash}" if repo_web_base and c.hash else "",
                    is_open=False,
                    thread_id=f"commit:{c.hash}",
                    thread_label=f"Commit {str(c.hash or '')[:7]}",
                    thread_url=f"{repo_web_base}/commit/{c.hash}" if repo_web_base and c.hash else "",
                    thread_is_open=False,
                )
                if doc:
                    _register_interaction_document(doc)

            for signal in window_gh_text_docs:
                dev_id = str(signal.get("developer_id") or "").strip()
                dev = dev_by_id.get(dev_id)
                if not dev:
                    continue
                doc = _build_interaction_document(
                    project=project,
                    window_meta=w,
                    source_type=str(signal.get("source_type") or "issue_pr"),
                    developer_id=dev_id,
                    role=dev.classification,
                    text=str(signal.get("text") or ""),
                    timestamp=signal.get("timestamp"),
                    source_id=str(signal.get("source_id") or ""),
                    source_label=str(signal.get("source_label") or ""),
                    source_url=str(signal.get("source_url") or ""),
                    is_open=bool(signal.get("is_open")),
                    thread_id=str(signal.get("thread_id") or ""),
                    thread_label=str(signal.get("thread_label") or ""),
                    thread_url=str(signal.get("thread_url") or ""),
                    thread_is_open=bool(signal.get("thread_is_open")),
                )
                if doc:
                    _register_interaction_document(doc)

            if is_latest_window:
                project.ml_detection_status = "Extracting role topics..."
                save_projects(projects_db)
                _ensure_topic_analysis_started()

            for s in community_smells:
                for entity_id in s.affected_entities:
                    dev = dev_by_id.get(entity_id)
                    if dev and s.smell_id not in dev.community_smells:
                        dev.community_smells.append(s.smell_id)

            for s in window_ml:
                for entity_id in s.affected_entities:
                    dev = dev_by_id.get(entity_id)
                    if not dev:
                        continue
                    if s.smell_id not in dev.ml_smells:
                        dev.ml_smells.append(s.smell_id)
                    rel = _to_repo_relative_path(s.file_path, history_repo_path)
                    dev.ml_smell_details.append({
                        "smell_id": s.smell_id,
                        "file": rel,
                        "line": s.line,
                        "message": s.message,
                    })

            for s in window_traditional:
                for entity_id in s.affected_entities:
                    dev = dev_by_id.get(entity_id)
                    if not dev:
                        continue
                    if s.smell_id not in dev.traditional_smells:
                        dev.traditional_smells.append(s.smell_id)
                    rel = _to_repo_relative_path(s.file_path, history_repo_path)
                    dev.traditional_smell_details.append({
                        "smell_id": s.smell_id,
                        "file": rel,
                        "line": s.line,
                        "message": s.message,
                    })

            for v in window_vulnerabilities:
                for entity_id in v.affected_entities:
                    dev = dev_by_id.get(entity_id)
                    if not dev:
                        continue
                    if v.vuln_id not in dev.vulnerabilities:
                        dev.vulnerabilities.append(v.vuln_id)
                    rel = _to_repo_relative_path(v.file_path, history_repo_path)
                    dev.vulnerability_details.append({
                        "vuln_id": v.vuln_id,
                        "name": v.name,
                        "severity": v.severity,
                        "confidence": v.confidence,
                        "file": rel,
                        "line": v.line,
                        "message": v.message,
                        "cwe": v.cwe,
                    })

            window_developers.sort(key=lambda d: (-(d.commits_count or 0), d.id))

            abandoned_ids: List[str] = sorted(
                [
                    dev_id
                    for dev_id in all_known_dev_ids
                    if dev_id and dev_id in last_active_window_idx and last_active_window_idx[dev_id] < idx
                ]
            )

            for dev in window_developers:
                last_idx = last_active_window_idx.get(dev.id)
                if last_idx is not None and 0 <= last_idx < len(windows):
                    dev.last_interaction_window_id = windows[last_idx]["id"]
                    dev.last_interaction_window_label = windows[last_idx]["label"]
                else:
                    dev.last_interaction_window_id = None
                    dev.last_interaction_window_label = None

                dev.is_abandoned = bool(last_idx is not None and last_idx < idx)
                dev.abandonment_status = "Abandoned" if dev.is_abandoned else "Active"
                last_commit = latest_commit_by_dev.get(dev.id)
                if last_commit:
                    dev.last_commit_hash = last_commit.hash
                    dev.last_commit_date = last_commit.date
                    dev.last_commit_message = last_commit.message
                else:
                    dev.last_commit_hash = None
                    dev.last_commit_date = None
                    dev.last_commit_message = None
                if dev.is_abandoned:
                    abandon_idx = int(last_idx + 1) if last_idx is not None else idx
                    if 0 <= abandon_idx < len(windows):
                        dev.abandoned_since_window_id = windows[abandon_idx]["id"]
                        dev.abandoned_since_window_label = windows[abandon_idx]["label"]
                        dev.abandoned_since_date = windows[abandon_idx]["start"]
                    else:
                        dev.abandoned_since_window_id = windows[idx]["id"]
                        dev.abandoned_since_window_label = windows[idx]["label"]
                        dev.abandoned_since_date = windows[idx]["start"]
                    dev.last_message_before_abandonment_hash = dev.last_commit_hash
                    dev.last_message_before_abandonment_date = dev.last_commit_date
                    dev.last_message_before_abandonment = dev.last_commit_message
                else:
                    dev.abandoned_since_window_id = None
                    dev.abandoned_since_window_label = None
                    dev.abandoned_since_date = None
                    dev.last_message_before_abandonment_hash = None
                    dev.last_message_before_abandonment_date = None
                    dev.last_message_before_abandonment = None

            dev_id_to_idx = {dev.id: i for i, dev in enumerate(window_developers)}
            edges = []
            for u, v, data in nb.collaboration_graph.edges(data=True):
                if u in dev_id_to_idx and v in dev_id_to_idx:
                    edges.append({
                        "from": dev_id_to_idx[u],
                        "to": dev_id_to_idx[v],
                        "weight": data.get("weight", 1),
                    })

            loc_est = int(snapshot_result["loc"] or 0)
            nom_est = int(snapshot_result["nom"] or 0)

            p_metrics = ProjectMetrics(
                project_id=project.id,
                time_window=w["label"],
                loc=loc_est,
                nom=nom_est,
            )

            p_metrics.community_smells_count = {}
            p_metrics.community_smell_instances = []
            for s in community_smells:
                p_metrics.community_smells_count[s.smell_id] = p_metrics.community_smells_count.get(s.smell_id, 0) + 1
                p_metrics.community_smell_instances.append({
                    "smell_id": s.smell_id,
                    "name": s.name,
                    "affected_entities": list(s.affected_entities or []),
                    "message": s.message,
                    "evidence": dict(s.evidence or {}),
                })

            p_metrics.ml_smells_count = {}
            for s in window_ml:
                p_metrics.ml_smells_count[s.smell_id] = p_metrics.ml_smells_count.get(s.smell_id, 0) + 1

            p_metrics.traditional_smells_count = {}
            for s in window_traditional:
                p_metrics.traditional_smells_count[s.smell_id] = p_metrics.traditional_smells_count.get(s.smell_id, 0) + 1

            p_metrics.vulnerabilities_count = {}
            p_metrics.vulnerabilities_severity_count = {}
            for v in window_vulnerabilities:
                p_metrics.vulnerabilities_count[v.vuln_id] = p_metrics.vulnerabilities_count.get(v.vuln_id, 0) + 1
                sev = (v.severity or "UNSPECIFIED").upper()
                p_metrics.vulnerabilities_severity_count[sev] = p_metrics.vulnerabilities_severity_count.get(sev, 0) + 1
            p_metrics.table3_metrics = table3_metrics
            p_metrics.abandoned_developers_count = len(abandoned_ids)
            p_metrics.abandoned_developers_ids = abandoned_ids

            snapshots.append(ProjectTimeWindow(
                id=w["id"],
                label=w["label"],
                start_date=w["start"],
                end_date=w["end_inclusive"],
                developers=window_developers,
                metrics=p_metrics,
                collaboration_edges=edges,
            ))

            processed_windows = idx + 1
            eta_seconds = _estimate_window_eta_seconds(project, windows_started_at, processed_windows, total_windows)
            _set_analysis_progress(
                project,
                20.0 + (70.0 * (float(processed_windows) / float(max(total_windows, 1)))),
                eta_seconds,
                processed_windows,
                total_windows,
            )
            if checkpoint_partial_results:
                project.time_windows = list(snapshots)
                latest_partial = snapshots[-1] if snapshots else None
                project.active_time_window_id = latest_partial.id if latest_partial else None
                if latest_partial:
                    project.developers = latest_partial.developers
                    project.metrics = [latest_partial.metrics]
                    project.collaboration_edges = latest_partial.collaboration_edges
                else:
                    project.developers = []
                    project.metrics = []
                    project.collaboration_edges = []
                _save_topic_documents(project.id, interaction_documents)
            _save_analysis_progress_state(force=is_latest_window)

        if _is_generation_cancelled(expected_generation):
            raise AnalysisCancelled("Analysis cancelled by Delete All Projects.")
        project.time_windows = snapshots
        _validate_time_windows(project.time_windows)
        _save_topic_documents(project.id, interaction_documents)
        latest_window = snapshots[-1] if snapshots else None
        project.active_time_window_id = latest_window.id if latest_window else None

        if latest_window:
            project.developers = latest_window.developers
            project.metrics = [latest_window.metrics]
            project.collaboration_edges = latest_window.collaboration_edges
        else:
            project.developers = []
            project.metrics = []
            project.collaboration_edges = []

        try:
            project.ml_detection_status = "Extracting role topics..."
            save_projects(projects_db)
            _ensure_topic_analysis_started()
            project.topic_modeling = topic_future.result() if topic_future is not None else topic_analyzer.analyze_documents(interaction_documents, scope_label=project.name)
        except Exception as e:
            project.topic_modeling = TopicModelingResult(
                status="Error",
                model=os.environ.get("SMELLHUB_TOPIC_MODEL", "gpt-5-mini"),
                generated_at=datetime.now(),
                source_count=len(interaction_documents),
                error=str(e),
            )

        project.analysis_status = "Completed"
        total_elapsed = max((datetime.now() - analysis_started_at).total_seconds(), 0.0)
        project.last_analysis_duration_seconds = float(round(total_elapsed, 2))
        project.last_analysis_window_count = int(total_windows)
        _set_analysis_progress(project, 100.0, 0, total_windows, total_windows)
        project.last_analyzed = datetime.now()
        _invalidate_global_topics_cache()
        save_projects(projects_db)

    except AnalysisCancelled as e:
        if project_id in projects_db:
            project.ml_detection_status = "Cancelled"
            project.ml_detection_error = str(e)
            project.analysis_status = "Cancelled"
            _set_analysis_progress(project, 0.0, None, 0, int(project.analysis_window_total or 0))
            save_projects(projects_db)
    except FileNotFoundError as e:
        print("run_full_analysis repository unavailable:")
        print(traceback.format_exc())
        project.ml_detection_status = "Repository unavailable"
        project.ml_detection_error = str(e)
        project.analysis_status = f"Error: Repository unavailable ({str(e)})"
        _set_analysis_progress(project, 0.0, None, 0, int(project.analysis_window_total or 0))
        save_projects(projects_db)
    except Exception as e:
        print("run_full_analysis failed:")
        print(traceback.format_exc())
        project.ml_detection_status = "Historical analysis failed"
        project.ml_detection_error = str(e)
        project.analysis_status = f"Error: {str(e)}"
        _set_analysis_progress(project, 0.0, None, 0, int(project.analysis_window_total or 0))
        save_projects(projects_db)
    finally:
        if topic_executor is not None:
            topic_executor.shutdown(wait=False, cancel_futures=False)
        if history_repo_path and os.path.exists(history_repo_path):
            shutil.rmtree(history_repo_path, ignore_errors=True)


@app.get("/projects/{project_id}", response_model=Project)
async def get_project(project_id: str):
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    return projects_db[project_id]


@app.post("/projects/{project_id}/topics/analyze", response_model=TopicModelingResult)
async def analyze_project_topics(project_id: str):
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")

    project = projects_db[project_id]
    documents = _collect_llm_only_documents(project)
    analyzer = RoleTopicModelingAnalyzer(config=_effective_llm_config())
    result = analyzer.analyze_documents(documents, scope_label=project.name)
    project.topic_modeling = result
    save_projects(projects_db)
    _invalidate_global_topics_cache()
    return result


@app.get("/topics/overall", response_model=TopicModelingResult)
async def get_overall_topics():
    with _GLOBAL_TOPICS_LOCK:
        return _GLOBAL_TOPICS_CACHE


@app.post("/topics/overall/analyze", response_model=TopicModelingResult)
async def analyze_overall_topics():
    global _GLOBAL_TOPICS_CACHE
    docs: List[Dict[str, Any]] = []
    skipped_projects: List[str] = []
    with _PROJECTS_DB_LOCK:
        projects = list(projects_db.values())
    for project in projects:
        project_docs = _load_topic_documents(project.id)
        if project_docs:
            docs.extend(project_docs)
        else:
            skipped_projects.append(project.name)

    if not docs:
        result = TopicModelingResult(
            status="No cached project LLM data",
            model=str(_effective_llm_config().get("model") or "gpt-5-mini"),
            generated_at=datetime.now(),
            source_count=0,
            taxonomy_notes=[
                "Run Project LLM Analysis on one or more projects first, then use Global LLM Analysis to aggregate them."
            ],
            error="Global LLM Analysis aggregates only project-level LLM datasets already prepared.",
        )
        with _GLOBAL_TOPICS_LOCK:
            _GLOBAL_TOPICS_CACHE = result
        return result

    analyzer = RoleTopicModelingAnalyzer(config=_effective_llm_config())
    result = analyzer.analyze_documents(docs, scope_label="All projects")
    if skipped_projects:
        result.taxonomy_notes = list(result.taxonomy_notes or []) + [
            f"Skipped projects without cached LLM data: {', '.join(skipped_projects[:8])}"
            + (" ..." if len(skipped_projects) > 8 else "")
        ]
    with _GLOBAL_TOPICS_LOCK:
        _GLOBAL_TOPICS_CACHE = result
    return result


_DEVELOPER_EXPORT_HEADER = [
    "project_url",
    "time_window_id",
    "time_window_label",
    "time_window_start",
    "time_window_end",
    "project_loc",
    "project_nom",
    "project_community_smells_total",
    "project_ml_smells_total",
    "project_traditional_smells_total",
    "project_vulnerabilities_total",
    "project_vulnerabilities_high",
    "project_vulnerabilities_medium",
    "project_vulnerabilities_low",
    "project_abandoned_developers_count",
    "project_abandoned_developers_ids",
    "project_collaboration_edges_count",
    "project_community_smells_count_json",
    "project_ml_smells_count_json",
    "project_traditional_smells_count_json",
    "project_vulnerabilities_count_json",
    "project_vulnerabilities_severity_count_json",
    "project_metrics_json",
    "project_community_smell_instances_json",
    "project_collaboration_edges_json",
    "Socio-Technical Quality Factors",
    "project_topic_status",
    "project_topic_model",
    "project_topic_judge_model",
    "project_topic_generated_at",
    "project_topic_source_count",
    "project_topic_discussion_source_count",
    "project_topic_llm_run_count",
    "project_topic_judged",
    "project_topic_source_breakdown_json",
    "project_topic_taxonomy_notes_json",
    "project_topic_roles_json",
    "project_topic_developers_json",
    "project_topic_conflicts_json",
    "project_topic_potential_conflict_threads_json",
    "project_topic_error",
    "project_topic_modeling_raw_json",
    "developer_id",
    "aliases",
    "emails",
    "classification",
    "gender",
    "gender_confidence",
    "gender_source",
    "pronouns_detected",
    "sentiment_label",
    "sentiment_score",
    "sentiment_messages_count",
    "abandonment_status",
    "is_abandoned",
    "last_interaction_window_id",
    "last_interaction_window_label",
    "abandoned_since_window_id",
    "abandoned_since_window_label",
    "abandoned_since_date",
    "last_commit_hash",
    "last_commit_date",
    "last_commit_message",
    "last_message_before_abandonment_hash",
    "last_message_before_abandonment_date",
    "last_message_before_abandonment",
    "se_score",
    "ai_score",
    "ml_score",
    "commits_count",
    "bug_fix_commits_count",
    "files_touched_count",
    "lines_added",
    "lines_deleted",
    "code_churn",
    "avg_files_per_commit",
    "bug_introduced_count_rszz",
    "community_smells",
    "community_smell_count",
    "ml_smells",
    "ml_smell_count",
    "ml_smell_instances",
    "traditional_smells",
    "traditional_smell_count",
    "traditional_smell_instances",
    "vulnerabilities",
    "vulnerability_count",
    "vulnerability_instances",
    "vulnerability_high",
    "vulnerability_medium",
    "vulnerability_low",
    "developer_topic_profile_json",
    "developer_topic_count",
    "developer_conflicts_json",
    "developer_conflict_count",
    "developer_open_conflict_count",
    "developer_potential_conflict_threads_json",
    "developer_potential_conflict_thread_count",
    "developer_raw_json",
]


def _write_project_developer_rows(
    writer: csv.writer,
    project: Project,
    window_id: Optional[str] = None,
    all_windows: bool = False,
) -> None:
    def _to_json_data(obj):
        if obj is None:
            return {}
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        if hasattr(obj, "dict"):
            return obj.dict()
        return obj

    topic_profiles_by_developer: Dict[str, Dict[str, Any]] = {}
    conflicts_by_developer: Dict[str, List[Dict[str, Any]]] = {}
    potential_threads_by_developer: Dict[str, List[Dict[str, Any]]] = {}
    topic_modeling = getattr(project, "topic_modeling", None)
    topic_modeling_json: Dict[str, Any] = _to_json_data(topic_modeling) if topic_modeling else {}
    topic_roles_json: List[Dict[str, Any]] = []
    topic_developers_json: List[Dict[str, Any]] = []
    topic_conflicts_json: List[Dict[str, Any]] = []
    topic_potential_threads_json: List[Dict[str, Any]] = []
    if topic_modeling:
        for role_row in (getattr(topic_modeling, "roles", []) or []):
            topic_roles_json.append(_to_json_data(role_row))

        for profile in (getattr(topic_modeling, "developers", []) or []):
            profile_json = _to_json_data(profile)
            topic_developers_json.append(profile_json)
            profile_dev_id = str(getattr(profile, "developer_id", "") or "").strip()
            if not profile_dev_id:
                continue
            topic_profiles_by_developer[profile_dev_id.casefold()] = profile_json

        for conflict in (getattr(topic_modeling, "conflicts", []) or []):
            conflict_json = _to_json_data(conflict)
            topic_conflicts_json.append(conflict_json)
            participant_ids = [
                str(pid or "").strip()
                for pid in (getattr(conflict, "participant_ids", []) or [])
                if str(pid or "").strip()
            ]
            involved_ids = {
                str(getattr(conflict, "developer_id", "") or "").strip(),
                str(getattr(conflict, "counterpart_id", "") or "").strip(),
                *participant_ids,
            }
            for involved_id in involved_ids:
                if not involved_id:
                    continue
                conflicts_by_developer.setdefault(involved_id.casefold(), []).append(conflict_json)

        for thread in (getattr(topic_modeling, "potential_conflict_threads", []) or []):
            thread_json = _to_json_data(thread)
            topic_potential_threads_json.append(thread_json)
            participant_ids = [
                str(pid or "").strip()
                for pid in (getattr(thread, "participant_ids", []) or [])
                if str(pid or "").strip()
            ]
            for participant_id in participant_ids:
                potential_threads_by_developer.setdefault(participant_id.casefold(), []).append(thread_json)

    rows = []
    if all_windows:
        for idx, tw in enumerate(project.time_windows or []):
            rows.append({
                "window_idx": idx,
                "window_id": tw.id,
                "window_label": tw.label,
                "window_start": tw.start_date.isoformat() if tw.start_date else "",
                "window_end": tw.end_date.isoformat() if tw.end_date else "",
                "developers": _window_export_developers(project, idx, tw.developers or []),
                "metrics": tw.metrics,
                "edges_count": len(tw.collaboration_edges or []),
                "collaboration_edges": tw.collaboration_edges or [],
            })
    else:
        window = _resolve_window(project, window_id)
        if window:
            resolved_idx = next((idx for idx, tw in enumerate(project.time_windows or []) if tw.id == window.id), None)
            rows.append({
                "window_idx": resolved_idx,
                "window_id": window.id,
                "window_label": window.label,
                "window_start": window.start_date.isoformat() if window.start_date else "",
                "window_end": window.end_date.isoformat() if window.end_date else "",
                "developers": _window_export_developers(project, resolved_idx, window.developers or []),
                "metrics": window.metrics,
                "edges_count": len(window.collaboration_edges or []),
                "collaboration_edges": window.collaboration_edges or [],
            })
        else:
            latest_metrics = project.metrics[0] if project.metrics else None
            latest_idx = len(project.time_windows or []) - 1 if (project.time_windows or []) else None
            rows.append({
                "window_idx": latest_idx,
                "window_id": "latest",
                "window_label": "latest",
                "window_start": "",
                "window_end": "",
                "developers": _window_export_developers(project, latest_idx, project.developers or []),
                "metrics": latest_metrics,
                "edges_count": len(project.collaboration_edges or []),
                "collaboration_edges": project.collaboration_edges or [],
            })

    for row in rows:
        metrics = row.get("metrics")
        community_smells_count = dict(getattr(metrics, "community_smells_count", {}) or {})
        ml_smells_count = dict(getattr(metrics, "ml_smells_count", {}) or {})
        traditional_smells_count = dict(getattr(metrics, "traditional_smells_count", {}) or {})
        vulnerabilities_count = dict(getattr(metrics, "vulnerabilities_count", {}) or {})
        vulnerabilities_severity_count = dict(getattr(metrics, "vulnerabilities_severity_count", {}) or {})
        table3_metrics = dict(getattr(metrics, "table3_metrics", {}) or {})
        metrics_json = _to_json_data(metrics)
        community_smell_instances = list(getattr(metrics, "community_smell_instances", []) or [])
        collaboration_edges = list(row.get("collaboration_edges") or [])

        for dev in (row.get("developers") or []):
            dev_key = str(dev.id or "").strip().casefold()
            dev_topic_profile = topic_profiles_by_developer.get(dev_key, {})
            dev_topics = list((dev_topic_profile or {}).get("topics", []) or [])
            dev_conflicts = list(conflicts_by_developer.get(dev_key, []) or [])
            dev_open_conflicts = sum(1 for conflict in dev_conflicts if bool(conflict.get("open_conflict", False)))
            dev_potential_threads = list(potential_threads_by_developer.get(dev_key, []) or [])
            writer.writerow([
                project.url or "",
                row["window_id"],
                row["window_label"],
                row["window_start"],
                row["window_end"],
                int(getattr(metrics, "loc", 0) or 0),
                int(getattr(metrics, "nom", 0) or 0),
                int(sum(community_smells_count.values())),
                int(sum(ml_smells_count.values())),
                int(sum(traditional_smells_count.values())),
                int(sum(vulnerabilities_count.values())),
                int(vulnerabilities_severity_count.get("HIGH", 0)),
                int(vulnerabilities_severity_count.get("MEDIUM", 0)),
                int(vulnerabilities_severity_count.get("LOW", 0)),
                int(getattr(metrics, "abandoned_developers_count", 0) or 0),
                " | ".join(getattr(metrics, "abandoned_developers_ids", []) or []),
                int(row.get("edges_count", 0) or 0),
                json.dumps(community_smells_count, ensure_ascii=True),
                json.dumps(ml_smells_count, ensure_ascii=True),
                json.dumps(traditional_smells_count, ensure_ascii=True),
                json.dumps(vulnerabilities_count, ensure_ascii=True),
                json.dumps(vulnerabilities_severity_count, ensure_ascii=True),
                json.dumps(metrics_json, ensure_ascii=True),
                json.dumps(community_smell_instances, ensure_ascii=True),
                json.dumps(collaboration_edges, ensure_ascii=True),
                json.dumps(table3_metrics, ensure_ascii=True),
                str(topic_modeling_json.get("status", "")),
                str(topic_modeling_json.get("model", "")),
                str(topic_modeling_json.get("judge_model", "")),
                str(topic_modeling_json.get("generated_at", "")),
                int(topic_modeling_json.get("source_count", 0) or 0),
                int(topic_modeling_json.get("discussion_source_count", 0) or 0),
                int(topic_modeling_json.get("llm_run_count", 0) or 0),
                bool(topic_modeling_json.get("judged", False)),
                json.dumps(dict(topic_modeling_json.get("source_breakdown", {}) or {}), ensure_ascii=True),
                json.dumps(list(topic_modeling_json.get("taxonomy_notes", []) or []), ensure_ascii=True),
                json.dumps(topic_roles_json, ensure_ascii=True),
                json.dumps(topic_developers_json, ensure_ascii=True),
                json.dumps(topic_conflicts_json, ensure_ascii=True),
                json.dumps(topic_potential_threads_json, ensure_ascii=True),
                str(topic_modeling_json.get("error", "") or ""),
                json.dumps(topic_modeling_json, ensure_ascii=True),
                dev.id,
                " | ".join(dev.aliases),
                " | ".join(dev.emails),
                dev.classification,
                dev.gender,
                dev.gender_confidence,
                dev.gender_source,
                " | ".join(dev.pronouns_detected),
                dev.sentiment_label,
                dev.sentiment_score,
                dev.sentiment_messages_count,
                dev.abandonment_status,
                dev.is_abandoned,
                dev.last_interaction_window_id or "",
                dev.last_interaction_window_label or "",
                dev.abandoned_since_window_id or "",
                dev.abandoned_since_window_label or "",
                dev.abandoned_since_date.isoformat() if dev.abandoned_since_date else "",
                dev.last_commit_hash or "",
                dev.last_commit_date.isoformat() if dev.last_commit_date else "",
                dev.last_commit_message or "",
                dev.last_message_before_abandonment_hash or "",
                dev.last_message_before_abandonment_date.isoformat() if dev.last_message_before_abandonment_date else "",
                dev.last_message_before_abandonment or "",
                dev.se_score,
                dev.ai_score,
                dev.ml_score,
                dev.commits_count,
                dev.bug_fix_commits_count,
                dev.files_touched_count,
                dev.lines_added,
                dev.lines_deleted,
                dev.code_churn,
                dev.avg_files_per_commit,
                dev.bug_introduced_count,
                " | ".join(dev.community_smells),
                len(dev.community_smells),
                " | ".join(dev.ml_smells),
                len(dev.ml_smells),
                len(dev.ml_smell_details),
                " | ".join(dev.traditional_smells),
                len(dev.traditional_smells),
                len(dev.traditional_smell_details),
                " | ".join(dev.vulnerabilities),
                len(dev.vulnerabilities),
                len(dev.vulnerability_details),
                sum(1 for x in dev.vulnerability_details if str(x.get("severity", "")).upper() == "HIGH"),
                sum(1 for x in dev.vulnerability_details if str(x.get("severity", "")).upper() == "MEDIUM"),
                sum(1 for x in dev.vulnerability_details if str(x.get("severity", "")).upper() == "LOW"),
                json.dumps(dev_topic_profile, ensure_ascii=True),
                len(dev_topics),
                json.dumps(dev_conflicts, ensure_ascii=True),
                len(dev_conflicts),
                dev_open_conflicts,
                json.dumps(dev_potential_threads, ensure_ascii=True),
                len(dev_potential_threads),
                json.dumps(_to_json_data(dev), ensure_ascii=True),
            ])


@app.get("/projects/{project_id}/developers/export.csv")
async def export_developers_csv(
    project_id: str,
    window_id: Optional[str] = None,
    all_windows: bool = False,
):
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")

    project = projects_db[project_id]

    sio = io.StringIO()
    writer = csv.writer(sio)
    writer.writerow(_DEVELOPER_EXPORT_HEADER)
    _write_project_developer_rows(writer, project, window_id=window_id, all_windows=all_windows)

    suffix = "all_history" if all_windows else (window_id or "latest")
    filename = f"{project.name.replace(' ', '_')}_developers_{suffix}.csv"
    return Response(
        content=sio.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/projects/developers/export-all.csv")
async def export_all_projects_developers_csv(all_windows: bool = True, analyzed_only: bool = True):
    sio = io.StringIO()
    writer = csv.writer(sio)
    writer.writerow(_DEVELOPER_EXPORT_HEADER)

    exported_projects = 0
    for project in projects_db.values():
        is_analyzed = bool(project.last_analyzed) or bool(project.time_windows) or bool(project.developers) or bool(project.metrics)
        if analyzed_only and not is_analyzed:
            continue
        _write_project_developer_rows(writer, project, window_id=None, all_windows=all_windows)
        exported_projects += 1

    if exported_projects == 0:
        raise HTTPException(status_code=404, detail="No analyzed projects available for export.")

    suffix = "all_history" if all_windows else "latest_only"
    filename = f"all_projects_developers_{suffix}.csv"
    return Response(
        content=sio.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


frontend_dir = os.path.join(RESOURCE_ROOT, "web", "frontend")
os.makedirs(frontend_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
