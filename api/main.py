from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from typing import List, Dict, Optional, Tuple, Any
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

import sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from models.schemas import (
    Project,
    ProjectMetrics,
    ProjectTimeWindow,
    SmellInstance,
    Developer,
    Commit,
    VulnerabilityInstance,
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

app = FastAPI(title="Community Smells Hub API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

import json

PROJECTS_FILE = os.path.join(PROJECT_ROOT, "data", "projects.json")
os.makedirs(os.path.dirname(PROJECTS_FILE), exist_ok=True)

_PRONOUN_FILE_CANDIDATES = [
    os.environ.get("PRONOUN_PARADIGMS_FILE", "").strip(),
    os.path.join(os.path.dirname(PROJECT_ROOT), "community_smells", "pronoun_paradigms_coling2022.txt"),
    "/Users/broke31/Desktop/community_smells/pronoun_paradigms_coling2022.txt",
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


def load_projects() -> Dict[str, Project]:
    if os.path.exists(PROJECTS_FILE):
        try:
            with open(PROJECTS_FILE, "r") as f:
                data = json.load(f)
                return {k: Project(**v) for k, v in data.items()}
        except Exception as e:
            print(f"Error loading projects: {e}")
    return {}


def save_projects(db: Dict[str, Project]):
    try:
        with open(PROJECTS_FILE, "w") as f:
            data = {k: v.model_dump(mode='json') for k, v in db.items()}
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving projects: {e}")


projects_db: Dict[str, Project] = load_projects()

_stale_running_fixed = False
for _p in projects_db.values():
    if _p.analysis_status == "Running":
        _p.analysis_status = "Interrupted (restart required)"
        _p.ml_detection_status = "Interrupted by server restart"
        if not _p.ml_detection_error:
            _p.ml_detection_error = "Previous background analysis stopped after backend restart."
        _stale_running_fixed = True
if _stale_running_fixed:
    save_projects(projects_db)


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
            text = f.read()
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


def _build_three_month_windows(commits: List[Commit]) -> List[Dict[str, object]]:
    if not commits:
        now = datetime.now()
        s = _start_of_month(now)
        e = _add_months(s, 3)
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
        nxt = _add_months(cursor, 3)
        windows.append({
            "id": _window_id(cursor, nxt),
            "label": _window_label(cursor, nxt),
            "start": cursor,
            "end_exclusive": nxt,
            "end_inclusive": nxt - timedelta(seconds=1),
        })
        cursor = nxt

    return windows


def _blame_line_info(repo_path: str, file_path: Optional[str], line: Optional[int]) -> Optional[Dict[str, object]]:
    if not file_path or not line:
        return None

    if os.path.isabs(file_path):
        file_abs = file_path
    else:
        file_abs = os.path.join(repo_path, file_path)

    if not os.path.exists(file_abs):
        return None

    rel = os.path.relpath(file_abs, repo_path)
    cmd = [
        "git", "-C", repo_path, "blame", "--line-porcelain",
        "-L", f"{line},{line}", rel,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except Exception:
        return None

    commit_hash = ""
    author_email = ""
    author_time = None

    for idx, row in enumerate(res.stdout.splitlines()):
        if idx == 0:
            parts = row.split()
            if parts:
                commit_hash = parts[0]
        if row.startswith("author-mail "):
            author_email = row.split(" ", 1)[1].strip().strip("<>").lower()
        elif row.startswith("author-time "):
            raw = row.split(" ", 1)[1].strip()
            try:
                author_time = datetime.fromtimestamp(int(raw))
            except Exception:
                author_time = None

    if not commit_hash and not author_email and not author_time:
        return None

    return {
        "commit_hash": commit_hash or None,
        "author_email": author_email or None,
        "author_date": author_time,
    }


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
    )


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


def _extract_login_from_noreply(email: str) -> Optional[str]:
    if not email:
        return None
    e = email.strip().lower()
    m = re.match(r"^(?:\d+\+)?([a-z0-9-]+)@users\.noreply\.github\.com$", e)
    if m:
        return m.group(1)
    return None


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
    for dev in developers:
        aliases_norm = {_normalize_identity_text(a) for a in (dev.aliases or []) if a}
        for email in dev.emails or []:
            login = _extract_login_from_noreply(email)
            if login:
                mapping[login.lower()] = dev.id
            local = (email or "").split("@", 1)[0].split("+")[-1].strip().lower()
            if local and re.match(r"^[a-z0-9-]{1,39}$", local):
                if _normalize_identity_text(local) in aliases_norm:
                    mapping[local] = dev.id
        for alias in dev.aliases or []:
            alias_s = (alias or "").strip().lower()
            if alias_s and re.match(r"^[a-z0-9-]{1,39}$", alias_s):
                mapping.setdefault(alias_s, dev.id)
    return mapping


def _fetch_github_issue_pr_interactions(
    project_url: str,
    start: datetime,
    end_exclusive: datetime,
    login_to_dev_id: Dict[str, str],
) -> List[Tuple[str, str, datetime]]:
    owner, repo = _parse_github_owner_repo(project_url)
    if not owner or not repo:
        return []

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    timeout_sec = 6

    def gh_get(url: str) -> Optional[Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "community-smells-hub",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(url, headers=headers, method="GET")
        try:
            with urlopen(req, timeout=timeout_sec) as res:
                if int(res.status) != 200:
                    return None
                return json.loads(res.read().decode("utf-8", errors="ignore"))
        except Exception:
            return None

    def add_pairwise_interactions(participants: set, ts: datetime, out: List[Tuple[str, str, datetime]], seen: set):
        ids = sorted({login_to_dev_id.get(p.lower()) for p in participants if p and login_to_dev_id.get(p.lower())})
        ids = [x for x in ids if x]
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

    interactions: List[Tuple[str, str, datetime]] = []
    seen = set()

    since_iso = start.isoformat() + "Z"
    for page in range(1, 6):
        issues = gh_get(
            f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/issues"
            f"?state=all&since={quote(since_iso)}&per_page=100&page={page}&sort=updated&direction=asc"
        )
        if not isinstance(issues, list) or not issues:
            break

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            number = issue.get("number")
            if not number:
                continue
            issue_dt = _parse_github_datetime(issue.get("updated_at") or issue.get("created_at"))
            if not issue_dt or issue_dt < start or issue_dt >= end_exclusive:
                continue

            participants = set()
            user = issue.get("user") or {}
            login = str(user.get("login") or "").strip()
            if login:
                participants.add(login)

            for assignee in issue.get("assignees") or []:
                if isinstance(assignee, dict):
                    l = str(assignee.get("login") or "").strip()
                    if l:
                        participants.add(l)

            comments = gh_get(
                f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/issues/{number}/comments?per_page=100"
            )
            if isinstance(comments, list):
                for c in comments:
                    if not isinstance(c, dict):
                        continue
                    cdt = _parse_github_datetime(c.get("created_at"))
                    if not cdt or cdt < start or cdt >= end_exclusive:
                        continue
                    cu = c.get("user") or {}
                    cl = str(cu.get("login") or "").strip()
                    if cl:
                        participants.add(cl)
                        add_pairwise_interactions(participants, cdt, interactions, seen)

            # Pull request specific interactions.
            if "pull_request" in issue:
                reviews = gh_get(
                    f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/pulls/{number}/reviews?per_page=100"
                )
                if isinstance(reviews, list):
                    for r in reviews:
                        if not isinstance(r, dict):
                            continue
                        rdt = _parse_github_datetime(r.get("submitted_at") or r.get("created_at"))
                        if not rdt or rdt < start or rdt >= end_exclusive:
                            continue
                        ru = r.get("user") or {}
                        rl = str(ru.get("login") or "").strip()
                        if rl:
                            participants.add(rl)
                            add_pairwise_interactions(participants, rdt, interactions, seen)

                pr_comments = gh_get(
                    f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/pulls/{number}/comments?per_page=100"
                )
                if isinstance(pr_comments, list):
                    for c in pr_comments:
                        if not isinstance(c, dict):
                            continue
                        pdt = _parse_github_datetime(c.get("created_at"))
                        if not pdt or pdt < start or pdt >= end_exclusive:
                            continue
                        pu = c.get("user") or {}
                        pl = str(pu.get("login") or "").strip()
                        if pl:
                            participants.add(pl)
                            add_pairwise_interactions(participants, pdt, interactions, seen)

            add_pairwise_interactions(participants, issue_dt, interactions, seen)

    return interactions


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
        self.github_token = os.environ.get("GITHUB_TOKEN", "").strip()
        self.max_profile_lookups = max(0, int(os.environ.get("GITHUB_PROFILE_LOOKUP_LIMIT", "120")))
        self.lookup_count = 0
        self.user_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self.contributor_logins: Optional[List[str]] = None

    def _get_json(self, url: str) -> Optional[Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "community-smells-hub",
        }
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"

        req = Request(url, headers=headers, method="GET")
        try:
            with urlopen(req, timeout=self.timeout_sec) as response:
                if int(response.status) != 200:
                    return None
                return json.loads(response.read().decode("utf-8", errors="ignore"))
        except Exception:
            return None

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

        for page in range(1, 3):
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

    cmd = ["git", "clone", project.url, repo_path]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        details = (e.stderr or e.stdout or str(e)).strip()
        raise RuntimeError(
            f"Failed to clone repository from {project.url} to {repo_path}. "
            f"Git said: {details[:700]}"
        ) from e


def _clone_repo_for_history(source_repo_path: str) -> str:
    clone_dir = tempfile.mkdtemp(prefix="history_repo_", dir="/tmp")
    cmd = ["git", "clone", "--quiet", "--no-checkout", source_repo_path, clone_dir]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return clone_dir


def _checkout_ref(repo_path: str, ref: str) -> None:
    cmd = ["git", "-C", repo_path, "checkout", "--quiet", ref]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


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
                    src = f.read()
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


def _allocate_repo_folder(repo_slug: str) -> str:
    base = os.path.join(PROJECT_ROOT, "data", "projects")
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


def _create_project_record(name: str, url: str = "", local_path: str = "") -> Project:
    project_id = str(uuid.uuid4())

    if local_path and os.path.isabs(local_path):
        final_path = local_path
        if not os.path.exists(final_path):
            raise ValueError(f"Local path does not exist: {final_path}")
    elif url:
        repo_slug = _sanitize_repo_slug(url)
        folder_name = local_path.strip("/") if local_path else repo_slug
        final_path = _allocate_repo_folder(folder_name)
        if not os.path.exists(final_path):
            from git import Repo
            Repo.clone_from(url, final_path)
    else:
        raise ValueError("Provide either a Git URL or an absolute local path.")

    project = Project(
        id=project_id,
        name=name,
        url=url,
        local_path=final_path,
        analysis_status="None",
    )
    projects_db[project_id] = project
    save_projects(projects_db)
    return project


class BulkRepoItem(BaseModel):
    url: str
    name: Optional[str] = None
    local_path: Optional[str] = ""


class BulkCreateRequest(BaseModel):
    repositories: List[BulkRepoItem] = Field(default_factory=list)
    auto_analyze: bool = True


@app.post("/projects", response_model=Project)
async def create_project(name: str, url: str = "", local_path: str = ""):
    try:
        return _create_project_record(name=name, url=url, local_path=local_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create project '{name}': {str(e)}")


@app.post("/projects/bulk")
async def create_projects_bulk(payload: BulkCreateRequest, background_tasks: BackgroundTasks):
    if not payload.repositories:
        raise HTTPException(status_code=400, detail="No repositories provided.")

    created: List[Dict[str, str]] = []
    errors: List[Dict[str, str]] = []

    for idx, item in enumerate(payload.repositories):
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
            project = _create_project_record(name=name, url=url, local_path=local_path)

            if payload.auto_analyze:
                project.analysis_status = "Running"
                background_tasks.add_task(run_full_analysis, project.id)

            created.append({
                "id": project.id,
                "name": project.name,
                "url": project.url,
                "status": project.analysis_status,
            })
        except ValueError as e:
            errors.append({
                "index": str(idx),
                "url": url,
                "name": name,
                "error": str(e),
            })
        except Exception as e:
            errors.append({
                "index": str(idx),
                "url": url,
                "name": name,
                "error": str(e),
            })

    if payload.auto_analyze and created:
        save_projects(projects_db)

    return {
        "requested": len(payload.repositories),
        "auto_analyze": payload.auto_analyze,
        "created": created,
        "errors": errors,
    }


@app.get("/projects", response_model=List[Project])
async def list_projects():
    return list(projects_db.values())


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")

    project = projects_db[project_id]
    used_by_other_projects = any(
        (p.id != project_id and p.local_path == project.local_path)
        for p in projects_db.values()
    )
    if (
        os.path.exists(project.local_path)
        and "data/projects" in project.local_path
        and not used_by_other_projects
    ):
        try:
            shutil.rmtree(project.local_path)
        except Exception as e:
            print(f"Failed to remove {project.local_path}: {e}")

    del projects_db[project_id]
    save_projects(projects_db)
    return {"message": "Project deleted successfully"}


@app.post("/projects/{project_id}/analyze")
async def start_analysis(project_id: str, background_tasks: BackgroundTasks):
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")

    project = projects_db[project_id]
    project.analysis_status = "Running"
    # Keep previous windows visible while the new analysis is running.
    save_projects(projects_db)

    background_tasks.add_task(run_full_analysis, project_id)
    return {"message": "Analysis started", "project_id": project_id}


def run_full_analysis(project_id: str):
    project = projects_db[project_id]
    history_repo_path: Optional[str] = None

    try:
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

        project.ml_detection_status = "Resolving developer profiles..."
        save_projects(projects_db)
        GitHubGenderResolver(project.url).annotate_developers(all_developers)

        base_dev_by_id: Dict[str, Developer] = {d.id: d for d in all_developers}
        email_to_dev_id = _build_email_to_dev_id(all_developers)

        project.ml_detection_status = "Running historical 3-month analysis..."
        save_projects(projects_db)

        dpy_binary = os.path.join(PROJECT_ROOT, "DPy")
        traditional_analyzer = TraditionalSmellAnalyzer(dpy_binary=dpy_binary)
        vuln_analyzer = BanditVulnerabilityAnalyzer()
        ml_analyzer = MLSmellAnalyzer()
        sentiment_analyzer = DeveloperSentimentAnalyzer(os.path.join(PROJECT_ROOT, "SE_Emotion_PTM-3589"))

        project.ml_detection_status = "Preparing developer sentiment model..."
        save_projects(projects_db)
        sentiment_ready = sentiment_analyzer.ensure_model_trained()
        if not sentiment_ready and sentiment_analyzer.last_error:
            print(f"Developer sentiment disabled: {sentiment_analyzer.last_error}")

        windows = _build_three_month_windows(commits)
        commits_sorted_asc = sorted(commits, key=lambda c: c.date)
        login_to_dev_id = _build_login_to_dev_id_map(all_developers)

        project_start = windows[0]["start"] if windows else datetime.now()
        project_end = windows[-1]["end_exclusive"] if windows else (project_start + timedelta(days=90))
        project.ml_detection_status = "Collecting PR/Issue communication..."
        save_projects(projects_db)
        gh_interactions_all = _fetch_github_issue_pr_interactions(
            project.url,
            project_start,
            project_end,
            login_to_dev_id,
        )

        cursor = 0
        for w in windows:
            end_exclusive = w["end_exclusive"]
            while cursor < len(commits_sorted_asc) and commits_sorted_asc[cursor].date < end_exclusive:
                cursor += 1
            snapshot_commit = commits_sorted_asc[cursor - 1] if cursor > 0 else None
            w["snapshot_commit_hash"] = snapshot_commit.hash if snapshot_commit else None

        snapshots: List[ProjectTimeWindow] = []
        classifier = DeveloperClassifier()
        rszz = RSZZAnalyzer(project.local_path)
        snapshot_cache: Dict[str, Dict[str, Any]] = {}
        prev_table3_state: Optional[Dict[str, set]] = None

        # R-SZZ is expensive: compute bug-inducing commits once, then assign each
        # event to its corresponding 3-month window.
        all_bic_hashes = rszz.identify_bug_inducing_commits(commits_sorted_asc)
        commit_by_hash = {c.hash: c for c in commits_sorted_asc}
        bic_events: List[Tuple[datetime, str]] = []
        for h in all_bic_hashes:
            c = commit_by_hash.get(h)
            if c and c.author_id:
                bic_events.append((c.date, c.author_id))
        bic_events.sort(key=lambda x: x[0])
        bic_cursor = 0

        history_repo_path = _clone_repo_for_history(project.local_path)

        for idx, w in enumerate(windows):
            start = w["start"]
            end_exclusive = w["end_exclusive"]
            is_latest_window = idx == (len(windows) - 1)
            snapshot_hash = str(w.get("snapshot_commit_hash") or "")
            window_commits = [c for c in commits_sorted_asc if start <= c.date < end_exclusive]
            snapshot_result: Dict[str, Any]

            if snapshot_hash:
                cached = snapshot_cache.get(snapshot_hash)
                if cached is None:
                    _checkout_ref(history_repo_path, snapshot_hash)
                    project.ml_detection_status = f"Analyzing {w['label']} ({idx + 1}/{len(windows)})"
                    save_projects(projects_db)

                    snap_ml = ml_analyzer.analyze_directory(history_repo_path, None)
                    snap_traditional = traditional_analyzer.analyze_directory(history_repo_path, email_to_dev_id)
                    snap_vulnerabilities = vuln_analyzer.analyze_directory(history_repo_path, email_to_dev_id)

                    ml_enriched = _attribute_instances_to_developers(
                        snap_ml, history_repo_path, email_to_dev_id, base_dev_by_id
                    )
                    traditional_enriched = _attribute_instances_to_developers(
                        snap_traditional, history_repo_path, email_to_dev_id, base_dev_by_id
                    )
                    vulnerabilities_enriched = _attribute_instances_to_developers(
                        snap_vulnerabilities, history_repo_path, email_to_dev_id, base_dev_by_id
                    )

                    loc_est, nom_est = _compute_loc_nom_for_snapshot(history_repo_path)

                    cached = {
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
                    snapshot_cache[snapshot_hash] = cached
                snapshot_result = cached
            else:
                snapshot_result = {
                    "ml_enriched": [],
                    "traditional_enriched": [],
                    "vulnerabilities_enriched": [],
                    "loc": 0,
                    "nom": 0,
                    "ml_status": "No commits available",
                    "ml_error": None,
                    "ml_stdout": None,
                    "ml_stderr": None,
                    "ml_call_graph_nodes": [],
                    "ml_call_graph_edges": [],
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

            classifier.classify_developers(window_developers, window_commits)
            _fill_developer_stats(window_developers, window_commits, window_bug_counts)
            if sentiment_ready:
                sentiment_analyzer.analyze_developers(window_developers, window_commits)

            nb = NetworkBuilder()
            nb.build_collaboration_network(window_commits)
            window_gh_interactions = [
                x for x in gh_interactions_all
                if start <= x[2] < end_exclusive
            ]
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

            snapshots.append(ProjectTimeWindow(
                id=w["id"],
                label=w["label"],
                start_date=w["start"],
                end_date=w["end_inclusive"],
                developers=window_developers,
                metrics=p_metrics,
                collaboration_edges=edges,
            ))

        project.time_windows = snapshots
        _validate_time_windows(project.time_windows)
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

        project.analysis_status = "Completed"
        project.last_analyzed = datetime.now()
        save_projects(projects_db)

    except Exception as e:
        print("run_full_analysis failed:")
        print(traceback.format_exc())
        project.ml_detection_status = "Historical analysis failed"
        project.ml_detection_error = str(e)
        project.analysis_status = f"Error: {str(e)}"
        save_projects(projects_db)
    finally:
        if history_repo_path and os.path.exists(history_repo_path):
            shutil.rmtree(history_repo_path, ignore_errors=True)


@app.get("/projects/{project_id}", response_model=Project)
async def get_project(project_id: str):
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    return projects_db[project_id]


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
    writer.writerow([
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
        "project_collaboration_edges_count",
        "project_community_smells_count_json",
        "project_ml_smells_count_json",
        "project_traditional_smells_count_json",
        "project_vulnerabilities_count_json",
        "project_vulnerabilities_severity_count_json",
        "Socio-Technical Quality Factors",
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
    ])

    rows = []
    if all_windows:
        for tw in (project.time_windows or []):
            rows.append({
                "window_id": tw.id,
                "window_label": tw.label,
                "window_start": tw.start_date.isoformat() if tw.start_date else "",
                "window_end": tw.end_date.isoformat() if tw.end_date else "",
                "developers": tw.developers or [],
                "metrics": tw.metrics,
                "edges_count": len(tw.collaboration_edges or []),
            })
    else:
        window = _resolve_window(project, window_id)
        if window:
            rows.append({
                "window_id": window.id,
                "window_label": window.label,
                "window_start": window.start_date.isoformat() if window.start_date else "",
                "window_end": window.end_date.isoformat() if window.end_date else "",
                "developers": window.developers or [],
                "metrics": window.metrics,
                "edges_count": len(window.collaboration_edges or []),
            })
        else:
            latest_metrics = project.metrics[0] if project.metrics else None
            rows.append({
                "window_id": "latest",
                "window_label": "latest",
                "window_start": "",
                "window_end": "",
                "developers": project.developers or [],
                "metrics": latest_metrics,
                "edges_count": len(project.collaboration_edges or []),
            })

    for row in rows:
        metrics = row.get("metrics")
        community_smells_count = dict(getattr(metrics, "community_smells_count", {}) or {})
        ml_smells_count = dict(getattr(metrics, "ml_smells_count", {}) or {})
        traditional_smells_count = dict(getattr(metrics, "traditional_smells_count", {}) or {})
        vulnerabilities_count = dict(getattr(metrics, "vulnerabilities_count", {}) or {})
        vulnerabilities_severity_count = dict(getattr(metrics, "vulnerabilities_severity_count", {}) or {})
        table3_metrics = dict(getattr(metrics, "table3_metrics", {}) or {})

        for dev in (row.get("developers") or []):
            writer.writerow([
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
                int(row.get("edges_count", 0) or 0),
                json.dumps(community_smells_count, ensure_ascii=True),
                json.dumps(ml_smells_count, ensure_ascii=True),
                json.dumps(traditional_smells_count, ensure_ascii=True),
                json.dumps(vulnerabilities_count, ensure_ascii=True),
                json.dumps(vulnerabilities_severity_count, ensure_ascii=True),
                json.dumps(table3_metrics, ensure_ascii=True),
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
            ])

    suffix = "all_history" if all_windows else (rows[0]["window_id"] if rows else "latest")
    filename = f"{project.name.replace(' ', '_')}_developers_{suffix}.csv"
    return Response(
        content=sio.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


frontend_dir = os.path.join(PROJECT_ROOT, "web", "frontend")
os.makedirs(frontend_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
