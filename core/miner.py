import os
import re
import uuid
import subprocess
from typing import List, Dict, Set, Optional
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
        cmd = [
            "git", "-C", self.repo_path, "log",
            "--numstat",
            "--format=COMMIT:%H|%ae|%an|%at|%P|%B%x00"
        ]
        if since:
            cmd.append(f"--since={since.isoformat()}")
        if until:
            cmd.append(f"--until={until.isoformat()}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True
            )
        except Exception as e:
            print(f"Error running git log: {e}")
            return []

        commits = []
        raw_output = result.stdout
        # Split by the "COMMIT:" marker followed by the hash format
        raw_chunks = raw_output.split("COMMIT:")[1:]
        
        for chunk in raw_chunks:
            # The chunk starts with hash|email|name|timestamp|parents|message\0
            # followed by the numstat lines
            try:
                header_part, numstat_part = chunk.split("\x00", 1)
            except ValueError:
                header_part = chunk
                numstat_part = ""
            
            parts = header_part.split("|", 5)
            if len(parts) < 6:
                continue
            
            commit_hash = parts[0]
            author_email = parts[1]
            author_name = parts[2]
            try:
                commit_timestamp = int(parts[3])
                commit_date = datetime.fromtimestamp(commit_timestamp)
            except ValueError:
                commit_date = datetime.now()
            
            # parts[4] is parents, parts[5] is message
            message = parts[5].strip()
            
            # Identify Bug Fixes
            is_bug_fix = False
            bug_id = None
            msg_lower = message.lower()
            if any(k in msg_lower for k in ["fix", "bug", "error", "issue", "resolve"]):
                is_bug_fix = True
                match = re.search(r'#(\d+)', msg_lower)
                if match:
                    bug_id = match.group(1)

            # Parse numstat
            files_modified = []
            lines_added = 0
            lines_deleted = 0
            
            for line in numstat_part.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                num_parts = line.split(None, 2)
                if len(num_parts) < 3:
                    continue
                try:
                    add = int(num_parts[0]) if num_parts[0] != '-' else 0
                    dele = int(num_parts[1]) if num_parts[1] != '-' else 0
                    file_path = num_parts[2]
                    
                    lines_added += add
                    lines_deleted += dele
                    files_modified.append(file_path)
                except ValueError:
                    continue

            person_id = self._get_person_id(author_name, author_email)
            
            commits.append(Commit(
                hash=commit_hash,
                author_id=person_id,
                date=commit_date,
                tz_offset_minutes=None, # git log %at gives UTC timestamp
                message=message,
                files_modified=files_modified,
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
