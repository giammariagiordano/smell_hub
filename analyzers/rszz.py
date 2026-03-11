import re
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from models.schemas import Commit

class RSZZAnalyzer:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def identify_bug_inducing_commits(self, all_commits: List[Commit]) -> List[str]:
        """
        R-SZZ approximation:
        1) take bug-fix commits (heuristic label in miner)
        2) extract deleted lines from fix diff (parent -> fix)
        3) blame those lines on parent revision
        4) filter cosmetic/meta candidates
        5) pick most recent candidate per fix commit
        """
        commit_by_hash: Dict[str, Commit] = {c.hash: c for c in all_commits}
        fix_commits = [c for c in all_commits if self._is_fix_commit(c)]
        inducing_hashes: Set[str] = set()

        for commit in fix_commits:
            candidates: Set[str] = set()
            for file_path in commit.files_modified:
                deleted = self._get_deleted_lines(commit.hash, file_path)
                if not deleted:
                    continue
                for line_no, line_content in deleted:
                    if self._is_cosmetic_line(line_content):
                        continue
                    blamed_hash = self._blame_line_before_fix(commit.hash, file_path, line_no)
                    if not blamed_hash:
                        continue
                    if blamed_hash == commit.hash:
                        continue
                    if self._is_meta_change(blamed_hash):
                        continue
                    candidates.add(blamed_hash)

            if not candidates:
                continue
            selected = self._select_most_recent(candidates, commit_by_hash)
            if selected:
                inducing_hashes.add(selected)

        return list(inducing_hashes)

    def count_bug_introduced_by_developer(self, all_commits: List[Commit]) -> Dict[str, int]:
        bics = self.identify_bug_inducing_commits(all_commits)
        hash_to_author = {c.hash: c.author_id for c in all_commits}
        counts: Dict[str, int] = {}
        for h in bics:
            author_id = hash_to_author.get(h)
            if not author_id:
                continue
            counts[author_id] = counts.get(author_id, 0) + 1
        return counts

    def _get_deleted_lines(self, fix_hash: str, file_path: str) -> List[Tuple[int, str]]:
        """
        Returns deleted lines as (line_number_in_parent, line_text) from unified diff -U0.
        """
        try:
            cmd = [
                "git", "diff", "--unified=0", "--no-color",
                f"{fix_hash}^", fix_hash, "--", file_path
            ]
            result = subprocess.run(cmd, cwd=self.repo_path, capture_output=True, text=True, check=True)
        except Exception:
            return []

        deleted: List[Tuple[int, str]] = []
        old_line = 0
        for raw in result.stdout.splitlines():
            if raw.startswith("@@"):
                # Example: @@ -10,2 +10,0 @@
                m = re.search(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
                if not m:
                    continue
                old_line = int(m.group(1))
                continue

            if raw.startswith("-") and not raw.startswith("---"):
                deleted.append((old_line, raw[1:]))
                old_line += 1
            elif raw.startswith("+") and not raw.startswith("+++"):
                # insertion in new file, old line pointer unchanged
                continue
            else:
                # context line
                old_line += 1
        return deleted

    def _blame_line_before_fix(self, fix_hash: str, file_path: str, line_no: int) -> Optional[str]:
        try:
            cmd = [
                "git", "blame", "--line-porcelain",
                "-L", f"{line_no},{line_no}",
                f"{fix_hash}^", "--", file_path
            ]
            result = subprocess.run(cmd, cwd=self.repo_path, capture_output=True, text=True, check=True)
        except Exception:
            return None

        first = result.stdout.splitlines()[0] if result.stdout else ""
        m = re.match(r"^([0-9a-f]{7,40})\s", first)
        return m.group(1) if m else None

    @staticmethod
    def _is_cosmetic_line(text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if stripped.startswith("#"):
            return True
        if stripped.startswith('"""') or stripped.startswith("'''"):
            return True
        return False

    def _is_meta_change(self, commit_hash: str) -> bool:
        try:
            parents_cmd = ["git", "rev-list", "--parents", "-n", "1", commit_hash]
            parents_res = subprocess.run(parents_cmd, cwd=self.repo_path, capture_output=True, text=True, check=True)
            fields = parents_res.stdout.strip().split()
            # commit + >=2 parents => merge commit
            if len(fields) > 2:
                return True
        except Exception:
            return False
        return False

    @staticmethod
    def _select_most_recent(candidates: Set[str], commit_by_hash: Dict[str, Commit]) -> Optional[str]:
        dated: List[Tuple[datetime, str]] = []
        for h in candidates:
            c = commit_by_hash.get(h)
            if c and c.date:
                dated.append((c.date, h))
        if dated:
            dated.sort(key=lambda x: x[0], reverse=True)
            return dated[0][1]
        # fallback when commit date not available in mined list
        return next(iter(candidates), None)

    @staticmethod
    def _is_fix_commit(commit: Commit) -> bool:
        msg = (commit.message or "").lower()
        negative_patterns = [
            "introduce bug",
            "bug introduced",
            "add bug",
            "reproduce bug",
        ]
        if any(p in msg for p in negative_patterns):
            return False

        positive_patterns = [
            "fix",
            "fixed",
            "fixes",
            "bugfix",
            "resolve",
            "resolved",
            "hotfix",
            "patch",
        ]
        return any(p in msg for p in positive_patterns)
