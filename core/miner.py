import os
import re
from typing import List, Dict, Set
from git import Repo
from datetime import datetime
from models.schemas import Commit, Developer

class RepositoryMiner:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.repo = Repo(repo_path)
        self.developer_map: Dict[str, Developer] = {}  # email -> Developer
        self.person_id_map: Dict[str, str] = {}  # email -> person_id

    def list_commits(self, since: datetime = None, until: datetime = None) -> List[Commit]:
        commits = []
        kwargs = {'rev': 'HEAD'}
        if since:
            kwargs['since'] = since
        if until:
            kwargs['until'] = until
            
        for git_commit in self.repo.iter_commits(**kwargs):
            author_email = git_commit.author.email
            author_name = git_commit.author.name
            tz_offset_minutes = None
            try:
                authored_dt = git_commit.authored_datetime
                if authored_dt and authored_dt.utcoffset() is not None:
                    tz_offset_minutes = int(authored_dt.utcoffset().total_seconds() // 60)
            except Exception:
                tz_offset_minutes = None
            
            # Basic Identity Matching
            person_id = self._get_person_id(author_name, author_email)
            
            # Identify Bug Fixes (Basic heuristic)
            is_bug_fix = False
            bug_id = None
            msg = git_commit.message.lower()
            if any(k in msg for k in ["fix", "bug", "error", "issue", "resolve"]):
                is_bug_fix = True
                # Try to extract bug ID
                match = re.search(r'#(\d+)', msg)
                if match:
                    bug_id = match.group(1)

            files = list(git_commit.stats.files.keys())
            lines_added = int(git_commit.stats.total.get('insertions', 0))
            lines_deleted = int(git_commit.stats.total.get('deletions', 0))
            
            commits.append(Commit(
                hash=git_commit.hexsha,
                author_id=person_id,
                date=datetime.fromtimestamp(git_commit.committed_date),
                tz_offset_minutes=tz_offset_minutes,
                message=git_commit.message,
                files_modified=files,
                is_bug_fix=is_bug_fix,
                bug_id=bug_id,
                lines_added=lines_added,
                lines_deleted=lines_deleted
            ))
            
        return commits

    def _get_person_id(self, name: str, email: str) -> str:
        # Standardize email and name
        email = email.lower().strip() if email else ""
        name = name.strip() if name else ""
        
        # Identity Matching Heuristics:
        # 1. Direct email match
        if email in self.person_id_map:
            person_id = self.person_id_map[email]
        else:
            # 2. Heuristic: Name normalization (lowercased alphanumeric)
            norm_name = re.sub(r'[^a-zA-Z0-9]', '', name.lower())
            
            # Check if this normalized name already mapped to someone
            matched_id = None
            for pid, dev in self.developer_map.items():
                for alias in dev.aliases:
                    if re.sub(r'[^a-zA-Z0-9]', '', alias.lower()) == norm_name:
                        matched_id = pid
                        break
                if matched_id: break
            
            if matched_id:
                person_id = matched_id
            else:
                # New person
                person_id = email or f"dev_{norm_name or uuid.uuid4().hex[:8]}"
            
            self.person_id_map[email] = person_id

        if person_id not in self.developer_map:
            self.developer_map[person_id] = Developer(
                id=person_id,
                aliases=[name] if name else [],
                emails=[email] if email else []
            )
        else:
            dev = self.developer_map[person_id]
            if name and name not in dev.aliases:
                dev.aliases.append(name)
            if email and email not in dev.emails:
                dev.emails.append(email)
                
        return person_id

    def get_developers(self) -> List[Developer]:
        return list(self.developer_map.values())
