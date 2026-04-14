import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from models.schemas import (
    DeveloperConflictRecord,
    DeveloperTopicProfile,
    PotentialConflictThread,
    RoleTopicTree,
    TopicModelingResult,
    TopicNode,
    TopicSubtopic,
    TraceabilityLink,
)


class RoleTopicModelingAnalyzer:
    ROLE_ORDER = ["Software Engineer", "AI/ML Engineer", "Hybrid"]
    DISCUSSION_SOURCE_TYPES = {"issue", "issue_comment", "pull_request", "review", "pr_comment"}
    CONFLICT_SIGNAL_PATTERNS = [
        ("changes_requested", re.compile(r"\bchanges?_requested\b|\bchanges?\s+requested\b|\brequest(?:ed)?\s+changes?\b", re.I)),
        ("blocked", re.compile(r"\bblock(?:ed|ing|er)?\b", re.I)),
        ("disagree", re.compile(r"\bdisagree\b|don't agree|do not agree", re.I)),
        ("reject", re.compile(r"\breject(?:ed|s|ing)?\b", re.I)),
        ("revert", re.compile(r"\brevert(?:ed|s|ing)?\b|\brollback\b|\bbackout\b", re.I)),
        ("concern", re.compile(r"\bconcern(?:s)?\b", re.I)),
        ("cannot_approve", re.compile(r"can't approve|cannot approve|won't approve|not approve", re.I)),
        ("needs_changes", re.compile(r"\bneeds?\s+changes?\b|\bmust fix\b|\bshould not\b|\bdoes not work\b|\bwon't work\b", re.I)),
    ]
    TRACEABILITY_SOURCE_PRIORITY = {
        "issue": 0,
        "pull_request": 1,
        "review": 2,
        "issue_comment": 3,
        "pr_comment": 4,
        "commit_message": 9,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = dict(config or {})
        self.api_key = (
            str(cfg.get("api_key") or "").strip()
            or os.environ.get("OPENAI_API_KEY", "").strip()
            or os.environ.get("SMELLHUB_OPENAI_API_KEY", "").strip()
        )
        self.organization = str(cfg.get("organization") or os.environ.get("OPENAI_ORGANIZATION", "")).strip()
        self.project = str(cfg.get("project") or os.environ.get("OPENAI_PROJECT", "")).strip()
        self.model = str(cfg.get("model") or os.environ.get("SMELLHUB_TOPIC_MODEL", "gpt-5-mini")).strip()
        self.judge_model = str(cfg.get("judge_model") or self.model).strip() or self.model
        self.endpoint = str(cfg.get("endpoint") or os.environ.get("SMELLHUB_OPENAI_CHAT_ENDPOINT", "https://api.openai.com/v1/chat/completions")).strip()
        try:
            requested_runs = int(cfg.get("llm_runs") if cfg.get("llm_runs") is not None else os.environ.get("SMELLHUB_TOPIC_RUNS", "1"))
        except Exception:
            requested_runs = 1
        self.run_count = max(1, min(7, requested_runs))
        self.max_docs_per_role = max(10, int(os.environ.get("SMELLHUB_TOPIC_MAX_DOCS_PER_ROLE", "80")))
        self.max_docs_per_developer = max(6, int(os.environ.get("SMELLHUB_TOPIC_MAX_DOCS_PER_DEVELOPER", "18")))
        self.max_threads = max(8, int(os.environ.get("SMELLHUB_TOPIC_MAX_THREADS", "60")))
        self.max_items_per_thread = max(3, int(os.environ.get("SMELLHUB_TOPIC_MAX_ITEMS_PER_THREAD", "12")))
        self.max_prompt_developers = max(6, int(os.environ.get("SMELLHUB_TOPIC_MAX_PROMPT_DEVELOPERS", "18")))
        self.max_prompt_threads = max(6, int(os.environ.get("SMELLHUB_TOPIC_MAX_PROMPT_THREADS", "24")))
        self.max_prompt_items_per_thread = max(2, int(os.environ.get("SMELLHUB_TOPIC_MAX_PROMPT_ITEMS_PER_THREAD", "6")))
        self.max_prompt_candidate_threads = max(4, int(os.environ.get("SMELLHUB_TOPIC_MAX_PROMPT_CONFLICT_THREADS", "10")))
        self.max_text_len = max(100, int(os.environ.get("SMELLHUB_TOPIC_MAX_TEXT_LEN", "260")))
        self.timeout_sec = max(30, int(os.environ.get("SMELLHUB_TOPIC_TIMEOUT_SEC", "180")))

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        if self.project:
            headers["OpenAI-Project"] = self.project
        return headers

    def _extract_message_content(self, body: Dict[str, Any]) -> str:
        content = (((body.get("choices") or [{}])[0].get("message") or {}).get("content"))
        if isinstance(content, list):
            joined = []
            for item in content:
                if isinstance(item, dict):
                    txt = item.get("text") or item.get("content") or ""
                    if txt:
                        joined.append(str(txt))
            content = "\n".join(joined)
        return str(content or "{}")

    def _format_openai_error(self, response: requests.Response) -> str:
        status = int(getattr(response, "status_code", 0) or 0)
        default = f"OpenAI request failed with HTTP {status}."
        try:
            body = response.json()
        except Exception:
            text = str(getattr(response, "text", "") or "").strip()
            if text:
                compact = re.sub(r"\s+", " ", text)
                return f"{default} Response body: {compact[:700]}"
            return default

        err = body.get("error") if isinstance(body, dict) else None
        if not isinstance(err, dict):
            compact = re.sub(r"\s+", " ", json.dumps(body, ensure_ascii=True))
            return f"{default} Response body: {compact[:700]}"

        message = str(err.get("message") or "").strip()
        err_type = str(err.get("type") or "").strip()
        err_param = str(err.get("param") or "").strip()
        err_code = str(err.get("code") or "").strip()
        parts = [default]
        if message:
            parts.append(message)
        meta = ", ".join(
            f"{label}={value}"
            for label, value in [
                ("type", err_type),
                ("param", err_param),
                ("code", err_code),
            ]
            if value
        )
        if meta:
            parts.append(f"({meta})")
        return " ".join(parts).strip()

    def _request_structured_json(
        self,
        *,
        model: str,
        schema_name: str,
        schema: Dict[str, Any],
        messages: List[Dict[str, str]],
        temperature: float,
    ) -> Dict[str, Any]:
        payload = {
            "model": model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        normalized_model = str(model or "").strip().lower()
        # GPT-5 chat-completions models reject custom temperature values and only accept the default.
        if normalized_model and not normalized_model.startswith("gpt-5"):
            payload["temperature"] = temperature
        response = requests.post(
            self.endpoint,
            headers=self._build_headers(),
            json=payload,
            timeout=self.timeout_sec,
        )
        if not response.ok:
            raise RuntimeError(self._format_openai_error(response))
        body = response.json()
        return json.loads(self._extract_message_content(body))

    def _run_candidate_analysis(self, scope_label: str, prepared: Dict[str, Any], run_index: int, total_runs: int) -> Dict[str, Any]:
        extra = ""
        if total_runs > 1:
            extra = (
                f"\n\nIndependent run metadata:\n"
                f"- run_index = {run_index + 1}\n"
                f"- total_runs = {total_runs}\n"
                "Produce an independent evidence-backed analysis. Do not try to optimize for stylistic similarity; optimize for factual consistency with the evidence."
            )
        return self._request_structured_json(
            model=self.model,
            schema_name="community_topics_and_conflicts",
            schema=self._response_schema(),
            messages=[
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": self._user_prompt(scope_label, prepared) + extra},
            ],
            temperature=min(0.65, 0.2 + (0.06 * run_index)),
        )

    def _judge_system_prompt(self) -> str:
        return (
            "You are an LLM judge comparing multiple structured analyses of the same software engineering evidence. "
            "Choose or synthesize the most evidence-backed, internally consistent final answer. "
            "Be conservative: prefer overlap between candidates, preserve traceability, and do not invent new facts or source ids. "
            "Resolve inconsistencies by favoring outputs that best match the evidence constraints: additive topic counts, empirical conflicts only, and consistent labels across roles."
        )

    def _judge_user_prompt(self, scope_label: str, prepared: Dict[str, Any], candidates: List[Dict[str, Any]]) -> str:
        compact_candidates = [
            {
                "run_index": int(item.get("run_index") or 0),
                "candidate": item.get("data") or {},
            }
            for item in candidates
        ]
        return (
            f"Scope: {scope_label}\n"
            "Judge the candidate analyses below and return a final_output that should be used as the canonical result.\n"
            "Rules:\n"
            "- Use only evidence and trace_source_ids already present in the candidates.\n"
            "- Prefer the most consistent candidate, but you may synthesize a better final_output if needed.\n"
            "- Keep topic labels canonical and reused across roles when semantics match.\n"
            "- Keep conflict detection conservative.\n"
            "- Keep topic counts additive across subtopics.\n\n"
            f"Source coverage summary:\n- source_breakdown = {json.dumps(prepared.get('source_breakdown') or {}, ensure_ascii=True)}\n"
            f"- discussion_source_count = {int(prepared.get('discussion_source_count') or 0)}\n"
            f"- candidate_count = {len(compact_candidates)}\n\n"
            "Candidates:\n"
            f"{json.dumps(compact_candidates, ensure_ascii=True)}"
        )

    def _judge_response_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "winner_index": {"type": "integer"},
                "rationale": {"type": "string"},
                "final_output": self._response_schema(),
            },
            "required": ["winner_index", "rationale", "final_output"],
        }

    def _conflict_judge_system_prompt(self) -> str:
        return (
            "You are an LLM judge validating developer-conflict extraction from software engineering discussions. "
            "Your job is to normalize confirmed conflict records so they align with issue and pull-request thread evidence, "
            "participant identity, and community labels. Be conservative: remove unsupported conflicts, do not invent source ids, "
            "and prefer issue / PR / review discussion evidence over commit-only inference whenever discussion sources exist."
        )

    def _conflict_judge_user_prompt(
        self,
        scope_label: str,
        prepared: Dict[str, Any],
        candidate_conflicts: List[Dict[str, Any]],
    ) -> str:
        discussion_threads = [
            {
                "thread_id": str(thread.get("thread_id") or ""),
                "thread_label": str(thread.get("thread_label") or ""),
                "thread_url": str(thread.get("thread_url") or ""),
                "source_type": str(thread.get("source_type") or ""),
                "is_open": bool(thread.get("is_open")),
                "participants": thread.get("participants") or [],
                "items": [
                    {
                        "source_id": str(item.get("source_id") or ""),
                        "developer_id": str(item.get("developer_id") or ""),
                        "role": str(item.get("role") or ""),
                        "source_type": str(item.get("source_type") or ""),
                        "label": str(item.get("label") or ""),
                    }
                    for item in (thread.get("items") or [])
                ],
            }
            for thread in (prepared.get("threads") or [])
            if str(thread.get("source_type") or "") in self.DISCUSSION_SOURCE_TYPES
        ][:20]
        return (
            f"Scope: {scope_label}\n"
            "Validate and normalize the developer conflict records below.\n"
            "Rules:\n"
            "- Use issue / PR / review thread evidence as the primary unit of conflict analysis.\n"
            "- Each confirmed conflict must be tied to a traced discussion thread.\n"
            "- participant_ids must include every developer directly involved in the evidenced disagreement thread.\n"
            "- participant_roles must use only canonical labels: Software Engineer, AI/ML Engineer, Hybrid.\n"
            "- role_combination must be derived from the full set of participant_roles, not only the two primary opponents.\n"
            "- If evidence is insufficient, remove the conflict instead of guessing.\n"
            "- Do not invent new trace_source_ids or developers.\n\n"
            f"Source coverage summary:\n- source_breakdown = {json.dumps(prepared.get('source_breakdown') or {}, ensure_ascii=True)}\n"
            f"- discussion_source_count = {int(prepared.get('discussion_source_count') or 0)}\n\n"
            "Discussion threads:\n"
            f"{json.dumps(discussion_threads, ensure_ascii=True)}\n\n"
            "Candidate conflicts:\n"
            f"{json.dumps(candidate_conflicts, ensure_ascii=True)}"
        )

    def _conflict_judge_response_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "rationale": {"type": "string"},
                "conflicts": self._response_schema()["properties"]["conflicts"],
            },
            "required": ["rationale", "conflicts"],
        }

    def _run_conflict_judge(
        self,
        *,
        scope_label: str,
        prepared: Dict[str, Any],
        final_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        raw_conflicts = final_data.get("conflicts") or []
        if not isinstance(raw_conflicts, list):
            raw_conflicts = []
        judge_result = self._request_structured_json(
            model=self.judge_model,
            schema_name="community_conflicts_judge",
            schema=self._conflict_judge_response_schema(),
            messages=[
                {"role": "system", "content": self._conflict_judge_system_prompt()},
                {
                    "role": "user",
                    "content": self._conflict_judge_user_prompt(scope_label, prepared, raw_conflicts),
                },
            ],
            temperature=0.0,
        )
        updated = dict(final_data)
        updated["conflicts"] = list(judge_result.get("conflicts") or [])
        rationale = str(judge_result.get("rationale") or "").strip()
        return updated, rationale

    def prepare_documents_incremental(self) -> Dict[str, Any]:
        return {
            "source_map": {},
            "source_breakdown": {},
            "documents_count_by_role": {role: 0 for role in self.ROLE_ORDER},
            "role_documents": {role: [] for role in self.ROLE_ORDER},
            "developer_documents": {},
            "developer_role_map": {},
            "thread_map": {},
            "source_count": 0,
            "document_index": 0,
        }

    def add_document_to_prepared(self, accumulator: Dict[str, Any], doc: Dict[str, Any]) -> bool:
        role = self._normalize_role(doc.get("role"))
        developer_id = str(doc.get("developer_id") or "").strip()
        text = self._clean_text(doc.get("text"))
        raw_source_id = str(doc.get("source_id") or "").strip()
        source_id = raw_source_id or (
            f"legacy:{doc.get('project_id') or 'project'}:"
            f"{doc.get('time_window_id') or 'window'}:"
            f"{developer_id}:{doc.get('source_type') or 'unknown'}:{int(accumulator.get('document_index') or 0)}"
        )
        if role not in self.ROLE_ORDER or not developer_id or not text:
            return False

        sort_key = (
            str(doc.get("timestamp") or ""),
            int(accumulator.get("document_index") or 0),
        )
        accumulator["document_index"] = int(accumulator.get("document_index") or 0) + 1
        accumulator["source_count"] = int(accumulator.get("source_count") or 0) + 1
        documents_count_by_role = accumulator.setdefault(
            "documents_count_by_role",
            {role_name: 0 for role_name in self.ROLE_ORDER},
        )
        documents_count_by_role[role] = int(documents_count_by_role.get(role, 0)) + 1

        developer_role_map = accumulator.setdefault("developer_role_map", {})
        developer_role_map[developer_id] = role

        source_row = {
            "source_id": source_id,
            "label": str(doc.get("source_label") or doc.get("thread_label") or source_id),
            "url": str(doc.get("source_url") or doc.get("thread_url") or ""),
            "source_type": str(doc.get("source_type") or ""),
            "is_open": bool(doc.get("is_open")),
            "thread_id": str(doc.get("thread_id") or source_id).strip() or source_id,
        }
        source_map = accumulator.setdefault("source_map", {})
        source_map[source_id] = source_row

        source_breakdown = accumulator.setdefault("source_breakdown", {})
        source_kind = source_row["source_type"]
        source_breakdown[source_kind] = int(source_breakdown.get(source_kind, 0)) + 1

        compact = {
            "source_id": source_id,
            "developer_id": developer_id,
            "role": role,
            "text": text,
            "source_type": source_row["source_type"],
            "label": source_row["label"],
            "is_open": source_row["is_open"],
            "thread_id": source_row["thread_id"],
            "_sort_key": sort_key,
        }

        role_documents = accumulator.setdefault("role_documents", {role_name: [] for role_name in self.ROLE_ORDER})
        role_documents.setdefault(role, []).append(compact)

        developer_documents = accumulator.setdefault("developer_documents", {})
        dev_row = developer_documents.get(developer_id)
        if dev_row is None:
            dev_row = {
                "developer_id": developer_id,
                "role": role,
                "documents_count": 0,
                "documents": [],
                "_latest_sort_key": sort_key,
            }
            developer_documents[developer_id] = dev_row
        dev_row["documents_count"] = int(dev_row.get("documents_count") or 0) + 1
        if sort_key >= tuple(dev_row.get("_latest_sort_key") or ("", -1)):
            dev_row["role"] = role
            dev_row["_latest_sort_key"] = sort_key
        dev_row.setdefault("documents", []).append(compact)

        thread_id = str(doc.get("thread_id") or source_id).strip()
        thread_map = accumulator.setdefault("thread_map", {})
        thread = thread_map.get(thread_id)
        if thread is None:
            thread = {
                "thread_id": thread_id,
                "thread_label": str(doc.get("thread_label") or source_row["label"]),
                "thread_url": str(doc.get("thread_url") or source_row["url"]),
                "source_type": source_row["source_type"],
                "is_open": bool(doc.get("thread_is_open", doc.get("is_open"))),
                "participants": {},
                "items": [],
                "_first_sort_key": sort_key,
            }
            thread_map[thread_id] = thread
        elif sort_key < tuple(thread.get("_first_sort_key") or ("", 0)):
            thread["thread_label"] = str(doc.get("thread_label") or source_row["label"])
            thread["thread_url"] = str(doc.get("thread_url") or source_row["url"])
            thread["source_type"] = source_row["source_type"]
            thread["is_open"] = bool(doc.get("thread_is_open", doc.get("is_open")))
            thread["_first_sort_key"] = sort_key
        thread["participants"][developer_id] = role
        thread["items"].append(compact)
        return True

    def finalize_prepared_documents(self, accumulator: Dict[str, Any]) -> Dict[str, Any]:
        role_documents = accumulator.get("role_documents") or {}
        role_samples: Dict[str, List[Dict[str, Any]]] = {role: [] for role in self.ROLE_ORDER}
        for role in self.ROLE_ORDER:
            rows = sorted(
                [item for item in (role_documents.get(role) or []) if isinstance(item, dict)],
                key=lambda item: item.get("_sort_key") or ("", 0),
            )[: self.max_docs_per_role]
            role_samples[role] = [self._strip_internal_sort_key(item) for item in rows]

        developer_samples = []
        developer_documents = accumulator.get("developer_documents") or {}
        for developer_id, developer in developer_documents.items():
            if not isinstance(developer, dict):
                continue
            docs = sorted(
                [item for item in (developer.get("documents") or []) if isinstance(item, dict)],
                key=lambda item: item.get("_sort_key") or ("", 0),
            )[: self.max_docs_per_developer]
            developer_samples.append(
                {
                    "developer_id": str(developer_id or ""),
                    "role": str(developer.get("role") or ""),
                    "documents_count": int(developer.get("documents_count") or 0),
                    "samples": [self._strip_internal_sort_key(item) for item in docs],
                }
            )
        developer_samples.sort(key=lambda item: (-(item.get("documents_count") or 0), str(item.get("developer_id") or "")))

        thread_map = accumulator.get("thread_map") or {}
        threads = []
        for thread in thread_map.values():
            if not isinstance(thread, dict):
                continue
            items = sorted(
                [item for item in (thread.get("items") or []) if isinstance(item, dict)],
                key=lambda item: item.get("_sort_key") or ("", 0),
            )[: self.max_items_per_thread]
            threads.append(
                {
                    "thread_id": str(thread.get("thread_id") or ""),
                    "thread_label": str(thread.get("thread_label") or ""),
                    "thread_url": str(thread.get("thread_url") or ""),
                    "source_type": str(thread.get("source_type") or ""),
                    "is_open": bool(thread.get("is_open")),
                    "participants": [
                        {"developer_id": dev_id, "role": role}
                        for dev_id, role in sorted((thread.get("participants") or {}).items())
                    ],
                    "items": [self._strip_internal_sort_key(item) for item in items],
                }
            )
        threads = sorted(
            threads,
            key=lambda item: (
                -(len(item.get("participants") or [])),
                -(len(item.get("items") or [])),
                str(item.get("thread_label") or ""),
            ),
        )[: self.max_threads]
        source_breakdown = dict(accumulator.get("source_breakdown") or {})
        discussion_source_count = sum(
            count for source_type, count in source_breakdown.items()
            if source_type in self.DISCUSSION_SOURCE_TYPES
        )
        potential_conflict_threads = self._collect_conflict_candidate_threads(threads)

        return {
            "source_count": int(accumulator.get("source_count") or 0),
            "source_map": dict(accumulator.get("source_map") or {}),
            "source_breakdown": source_breakdown,
            "discussion_source_count": discussion_source_count,
            "documents_count_by_role": dict(accumulator.get("documents_count_by_role") or {}),
            "developer_role_map": dict(accumulator.get("developer_role_map") or {}),
            "role_samples": role_samples,
            "developer_samples": developer_samples,
            "potential_conflict_threads": potential_conflict_threads,
            "threads": threads,
        }

    def _strip_internal_sort_key(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in item.items() if key != "_sort_key"}

    def analyze_prepared_documents(self, prepared: Dict[str, Any], scope_label: str) -> TopicModelingResult:
        source_count = int(prepared.get("source_count", 0))
        source_map = dict(prepared.get("source_map") or {})
        developer_role_map = dict(prepared.get("developer_role_map") or {})
        counts_by_role = dict(prepared.get("documents_count_by_role") or {})

        if source_count <= 0:
            return TopicModelingResult(
                status="No interaction data",
                model=self.model,
                judge_model=self.judge_model if self.run_count > 1 else "",
                generated_at=datetime.now(),
                source_count=0,
                discussion_source_count=0,
                llm_run_count=self.run_count,
                judged=False,
                source_breakdown={},
                roles=[RoleTopicTree(role=role, documents_count=0, topics=[]) for role in self.ROLE_ORDER],
                developers=[],
                conflicts=[],
            )

        if not self.is_configured():
            return TopicModelingResult(
                status="Skipped (missing OPENAI_API_KEY)",
                model=self.model,
                judge_model=self.judge_model if self.run_count > 1 else "",
                generated_at=datetime.now(),
                source_count=source_count,
                discussion_source_count=int(prepared.get("discussion_source_count") or 0),
                llm_run_count=self.run_count,
                judged=False,
                source_breakdown=dict(prepared.get("source_breakdown") or {}),
                roles=[
                    RoleTopicTree(role=role, documents_count=int(counts_by_role.get(role, 0)), topics=[])
                    for role in self.ROLE_ORDER
                ],
                developers=[],
                conflicts=[],
                potential_conflict_threads=self._build_potential_conflicts(prepared, source_map),
                error="Set OPENAI_API_KEY (or SMELLHUB_OPENAI_API_KEY) on the backend to enable topic and conflict extraction.",
            )

        try:
            candidate_runs: List[Dict[str, Any]] = []
            candidate_errors: List[str] = []
            if self.run_count <= 1:
                try:
                    candidate_data = self._run_candidate_analysis(scope_label, prepared, 0, self.run_count)
                    candidate_runs.append({"run_index": 1, "data": candidate_data})
                except Exception as run_error:
                    candidate_errors.append(f"run 1: {str(run_error)}")
            else:
                with ThreadPoolExecutor(max_workers=self.run_count) as pool:
                    future_map = {
                        pool.submit(
                            self._run_candidate_analysis,
                            scope_label,
                            prepared,
                            run_index,
                            self.run_count,
                        ): run_index
                        for run_index in range(self.run_count)
                    }
                    successful_runs: Dict[int, Dict[str, Any]] = {}
                    for future in as_completed(future_map):
                        run_index = future_map[future]
                        try:
                            successful_runs[run_index] = future.result()
                        except Exception as run_error:
                            candidate_errors.append(f"run {run_index + 1}: {str(run_error)}")
                    for run_index in range(self.run_count):
                        candidate_data = successful_runs.get(run_index)
                        if candidate_data is not None:
                            candidate_runs.append({"run_index": run_index + 1, "data": candidate_data})

            if not candidate_runs:
                raise RuntimeError("All LLM runs failed. " + " | ".join(candidate_errors[:4]))

            judged = False
            judge_notes: List[str] = []
            final_data = candidate_runs[0]["data"]
            if len(candidate_runs) >= 2:
                try:
                    judge_result = self._request_structured_json(
                        model=self.judge_model,
                        schema_name="community_topics_and_conflicts_judge",
                        schema=self._judge_response_schema(),
                        messages=[
                            {"role": "system", "content": self._judge_system_prompt()},
                            {"role": "user", "content": self._judge_user_prompt(scope_label, prepared, candidate_runs)},
                        ],
                        temperature=0.0,
                    )
                    judged = True
                    final_data = dict(judge_result.get("final_output") or final_data)
                    winner_index = max(1, int(judge_result.get("winner_index") or 1))
                    rationale = str(judge_result.get("rationale") or "").strip()
                    judge_note = f"Judge selected run {winner_index} from {len(candidate_runs)} successful runs."
                    if rationale:
                        judge_note += f" Rationale: {rationale}"
                    judge_notes.append(judge_note)
                except Exception as judge_error:
                    judge_notes.append(
                        f"Judge step failed after {len(candidate_runs)} successful runs; "
                        f"fallback used run 1. Judge error: {str(judge_error)}"
                    )
            try:
                final_data, conflict_judge_rationale = self._run_conflict_judge(
                    scope_label=scope_label,
                    prepared=prepared,
                    final_data=final_data,
                )
                judged = True
                note = "Conflict judge normalized participant coverage and community labels."
                if conflict_judge_rationale:
                    note += f" Rationale: {conflict_judge_rationale}"
                judge_notes.append(note)
            except Exception as conflict_judge_error:
                judge_notes.append(f"Conflict judge step failed; keeping pre-judge conflicts. Error: {str(conflict_judge_error)}")

            return self._build_result(
                final_data,
                source_count,
                source_map,
                developer_role_map,
                counts_by_role,
                prepared,
                llm_run_count=self.run_count,
                judged=judged,
                judge_model=self.judge_model if judged else "",
                extra_notes=judge_notes + (
                    [f"{len(candidate_errors)} run(s) failed during multi-run execution."] if candidate_errors else []
                ),
            )
        except Exception as e:
            return TopicModelingResult(
                status="Error",
                model=self.model,
                judge_model=self.judge_model if self.run_count > 1 else "",
                generated_at=datetime.now(),
                source_count=source_count,
                discussion_source_count=int(prepared.get("discussion_source_count") or 0),
                llm_run_count=self.run_count,
                judged=False,
                source_breakdown=dict(prepared.get("source_breakdown") or {}),
                roles=[
                    RoleTopicTree(role=role, documents_count=int(counts_by_role.get(role, 0)), topics=[])
                    for role in self.ROLE_ORDER
                ],
                developers=[],
                conflicts=[],
                potential_conflict_threads=self._build_potential_conflicts(prepared, source_map),
                error=str(e),
            )

    def analyze_documents(self, documents: List[Dict[str, Any]], scope_label: str) -> TopicModelingResult:
        prepared = self._prepare_documents(documents or [])
        return self.analyze_prepared_documents(prepared, scope_label)

    def _prepare_documents(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        accumulator = self.prepare_documents_incremental()
        sorted_docs = sorted(documents, key=lambda d: str(d.get("timestamp") or ""))
        for doc in sorted_docs:
            if isinstance(doc, dict):
                self.add_document_to_prepared(accumulator, doc)
        return self.finalize_prepared_documents(accumulator)

    def _system_prompt(self) -> str:
        return (
            "You analyze software engineering community interaction at developer granularity. "
            "Your job is to do two things from empirical evidence only: "
            "(1) extract coherent topic trees with traceability, and "
            "(2) identify genuine developer conflicts. "
            "A conflict must show disagreement, blocking, rejected proposals, antagonistic review, changes requested on a contested proposal, revert/backout behavior, "
            "or persistent unresolved tension about a concrete technical decision. Do not mark normal coordination or neutral discussion as conflict. "
            "Reuse the same exact topic and subtopic labels across roles whenever the theme is the same. "
            "When a conflict appears resolved, explain briefly how it was resolved using evidence from the discussion or follow-up commits. "
            "Prefer issue, pull-request, review, and review-comment evidence over commit-only inference whenever discussion sources exist."
        )

    def _user_prompt(self, scope_label: str, prepared: Dict[str, Any]) -> str:
        source_breakdown = prepared.get("source_breakdown") or {}
        source_breakdown_json = json.dumps(source_breakdown, ensure_ascii=True)
        candidate_threads = prepared.get("potential_conflict_threads") or []
        prompt_payload = self._build_prompt_payload(prepared)
        return (
            f"Scope: {scope_label}\n"
            "Sources are issue tracker discussions, pull requests, code reviews, and commit messages.\n"
            "You must return:\n"
            "- role-level topic trees with trace_source_ids\n"
            "- developer-level topic profiles with trace_source_ids\n"
            "- developer conflict records with trace_source_ids\n\n"
            "Topic counting rules:\n"
            "- evidence_count must be coherent with the tree.\n"
            "- If a topic has subtopics, topic.evidence_count must equal the sum of its direct subtopics' evidence_count values.\n"
            "- Within the same parent topic, do not assign the same evidence item to multiple sibling subtopics.\n"
            "- Use trace_source_ids that support the assigned topic or subtopic empirically.\n\n"
            "Conflict rules:\n"
            "- Use issue / PR / review threads as the primary unit for conflict identification whenever they exist.\n"
            "- First identify which issue / PR thread contains the disagreement, then identify the developers involved in that thread.\n"
            "- Only report conflicts backed by evidence.\n"
            "- Each conflict record must represent one concrete disagreement case, not a vague relationship.\n"
            "- Set conflict_title to a short canonical label describing the disputed topic or decision.\n"
            "- developer_id and counterpart_id must be the primary opposing developers; participant_ids must include every directly involved developer evidenced in the thread.\n"
            "- participant_roles must align with participant_ids and use the canonical role labels from the input.\n"
            "- role_combination must reflect all communities present in participant_roles using canonical labels and x separators.\n"
            "- Conflicts can be intra-community or cross-community, and the community combination is part of the required output semantics.\n"
            "- Prefer discussion evidence from issue / pull_request / review / pr_comment / issue_comment. If any such evidence exists for a conflict, primary_trace_source_id must point to one of those discussion sources, not a commit.\n"
            "- Use commit-only evidence only when the commit text itself explicitly shows revert/backout/disagreement and no discussion source is available.\n"
            "- A conflict is open only if the supporting issue/PR thread is still open or the evidence clearly shows unresolved blocking.\n"
            "- Set status to a short canonical label such as open, resolved, or closed_without_clear_resolution.\n"
            "- If resolved, resolution_summary must explain how the disagreement ended. If closed without a clear resolution, say that explicitly. If unresolved, leave resolution_summary empty.\n"
            "- summary must say what the conflict was about in concrete engineering terms.\n"
            "- Use the exact developer ids given in input.\n"
            "- Keep output at developer granularity.\n"
            "- If there is no empirical evidence for a real conflict, return no conflict record.\n\n"
            f"Source coverage summary:\n- source_breakdown = {source_breakdown_json}\n"
            f"- discussion_source_count = {int(prepared.get('discussion_source_count') or 0)}\n"
            f"- potential_conflict_candidate_threads = {len(candidate_threads)}\n\n"
            "Potential conflict candidate threads:\n"
            f"{json.dumps(candidate_threads[:12], ensure_ascii=True)}\n\n"
            "Input payload:\n"
            f"{json.dumps(prompt_payload, ensure_ascii=True)}"
        )

    def _build_prompt_payload(self, prepared: Dict[str, Any]) -> Dict[str, Any]:
        role_samples = {}
        for role in self.ROLE_ORDER:
            rows = [
                {
                    "source_id": str(item.get("source_id") or ""),
                    "developer_id": str(item.get("developer_id") or ""),
                    "role": str(item.get("role") or ""),
                    "source_type": str(item.get("source_type") or ""),
                    "label": str(item.get("label") or ""),
                    "is_open": bool(item.get("is_open")),
                    "text": str(item.get("text") or ""),
                }
                for item in (prepared.get("role_samples") or {}).get(role, [])[: self.max_docs_per_role]
                if isinstance(item, dict)
            ]
            if rows:
                role_samples[role] = rows

        developer_samples = []
        for developer in (prepared.get("developer_samples") or [])[: self.max_prompt_developers]:
            if not isinstance(developer, dict):
                continue
            developer_samples.append(
                {
                    "developer_id": str(developer.get("developer_id") or ""),
                    "role": str(developer.get("role") or ""),
                    "documents_count": int(developer.get("documents_count") or 0),
                    "samples": [
                        {
                            "source_id": str(item.get("source_id") or ""),
                            "source_type": str(item.get("source_type") or ""),
                            "label": str(item.get("label") or ""),
                            "is_open": bool(item.get("is_open")),
                            "text": str(item.get("text") or ""),
                        }
                        for item in (developer.get("samples") or [])[: self.max_docs_per_developer]
                        if isinstance(item, dict)
                    ],
                }
            )

        threads = []
        for thread in (prepared.get("threads") or [])[: self.max_prompt_threads]:
            if not isinstance(thread, dict):
                continue
            threads.append(
                {
                    "thread_id": str(thread.get("thread_id") or ""),
                    "thread_label": str(thread.get("thread_label") or ""),
                    "thread_url": str(thread.get("thread_url") or ""),
                    "source_type": str(thread.get("source_type") or ""),
                    "is_open": bool(thread.get("is_open")),
                    "participants": [
                        {
                            "developer_id": str(item.get("developer_id") or ""),
                            "role": str(item.get("role") or ""),
                        }
                        for item in (thread.get("participants") or [])
                        if isinstance(item, dict)
                    ],
                    "items": [
                        {
                            "source_id": str(item.get("source_id") or ""),
                            "developer_id": str(item.get("developer_id") or ""),
                            "role": str(item.get("role") or ""),
                            "source_type": str(item.get("source_type") or ""),
                            "label": str(item.get("label") or ""),
                            "is_open": bool(item.get("is_open")),
                            "text": str(item.get("text") or ""),
                        }
                        for item in (thread.get("items") or [])[: self.max_prompt_items_per_thread]
                        if isinstance(item, dict)
                    ],
                }
            )

        return {
            "source_count": int(prepared.get("source_count") or 0),
            "source_breakdown": dict(prepared.get("source_breakdown") or {}),
            "discussion_source_count": int(prepared.get("discussion_source_count") or 0),
            "documents_count_by_role": dict(prepared.get("documents_count_by_role") or {}),
            "role_samples": role_samples,
            "developer_samples": developer_samples,
            "threads": threads,
            "potential_conflict_threads": [
                item
                for item in (prepared.get("potential_conflict_threads") or [])[: self.max_prompt_candidate_threads]
                if isinstance(item, dict)
            ],
        }

    def _build_result(
        self,
        data: Dict[str, Any],
        source_count: int,
        source_map: Dict[str, Dict[str, Any]],
        developer_role_map: Dict[str, str],
        counts_by_role: Dict[str, int],
        prepared: Dict[str, Any],
        llm_run_count: int = 1,
        judged: bool = False,
        judge_model: str = "",
        extra_notes: Optional[List[str]] = None,
    ) -> TopicModelingResult:
        raw_roles = data.get("roles") or []
        raw_developers = data.get("developers") or []
        raw_conflicts = data.get("conflicts") or []
        thread_map = self._threads_by_id(prepared)

        role_rows: List[RoleTopicTree] = []
        raw_roles_by_name = {
            self._normalize_role(item.get("role")): item
            for item in raw_roles
            if isinstance(item, dict)
        }
        for role in self.ROLE_ORDER:
            role_item = raw_roles_by_name.get(role) or {}
            role_rows.append(
                RoleTopicTree(
                    role=role,
                    summary=str(role_item.get("summary") or "").strip(),
                    documents_count=int(counts_by_role.get(role, 0)),
                    topics=self._build_topics(role_item.get("topics") or [], source_map),
                )
            )

        developer_rows: List[DeveloperTopicProfile] = []
        for raw_dev in raw_developers:
            if not isinstance(raw_dev, dict):
                continue
            developer_id = str(raw_dev.get("developer_id") or "").strip()
            if not developer_id:
                continue
            developer_rows.append(
                DeveloperTopicProfile(
                    developer_id=developer_id,
                    role=developer_role_map.get(developer_id, self._normalize_role(raw_dev.get("role"))),
                    documents_count=max(0, int(raw_dev.get("documents_count") or 0)),
                    summary=str(raw_dev.get("summary") or "").strip(),
                    topics=self._build_topics(raw_dev.get("topics") or [], source_map),
                    trace_links=self._trace_links_from_ids(raw_dev.get("trace_source_ids") or [], source_map),
                )
            )
        developer_rows.sort(key=lambda item: (item.role, item.developer_id))

        conflict_rows: List[DeveloperConflictRecord] = []
        for raw_conflict in raw_conflicts:
            if not isinstance(raw_conflict, dict):
                continue
            developer_id = str(raw_conflict.get("developer_id") or "").strip()
            counterpart_id = str(raw_conflict.get("counterpart_id") or "").strip()
            if not developer_id or not counterpart_id:
                continue
            developer_role = developer_role_map.get(developer_id, "Unknown")
            counterpart_role = developer_role_map.get(counterpart_id, "Unknown")
            participant_ids = self._conflict_participants_with_thread_context(
                raw_conflict,
                developer_id,
                counterpart_id,
                source_map,
                thread_map,
            )
            participant_roles = self._normalize_conflict_roles(
                raw_conflict,
                developer_id,
                counterpart_id,
                developer_role_map,
                participant_ids=participant_ids,
            )
            conflict_rows.append(
                DeveloperConflictRecord(
                    conflict_title=str(raw_conflict.get("conflict_title") or "").strip(),
                    developer_id=developer_id,
                    developer_role=developer_role,
                    counterpart_id=counterpart_id,
                    counterpart_role=counterpart_role,
                    participant_ids=participant_ids,
                    participant_roles=participant_roles,
                    role_combination=self._conflict_role_combination(
                        raw_conflict,
                        developer_id,
                        counterpart_id,
                        developer_role_map,
                        participant_ids=participant_ids,
                        participant_roles=participant_roles,
                    ),
                    status=str(raw_conflict.get("status") or "unknown").strip(),
                    summary=str(raw_conflict.get("summary") or "").strip(),
                    resolution_summary=str(raw_conflict.get("resolution_summary") or "").strip(),
                    evidence_count=max(0, int(raw_conflict.get("evidence_count") or 0)),
                    open_conflict=bool(raw_conflict.get("open_conflict") or self._raw_conflict_is_open(raw_conflict, source_map)),
                    primary_link=self._primary_trace_link(
                        str(raw_conflict.get("primary_trace_source_id") or "").strip(),
                        raw_conflict.get("trace_source_ids") or [],
                        source_map,
                    ),
                    source_links=self._trace_links_from_ids(raw_conflict.get("trace_source_ids") or [], source_map),
                )
            )
        conflict_rows.sort(key=lambda item: (item.role_combination, item.developer_id, item.counterpart_id))
        potential_conflicts = self._build_potential_conflicts(prepared, source_map)
        taxonomy_notes = [str(x).strip() for x in (data.get("taxonomy_notes") or []) if str(x).strip()][:8]
        source_breakdown = dict(prepared.get("source_breakdown") or {})
        discussion_source_count = int(prepared.get("discussion_source_count") or 0)
        if source_breakdown:
            mix = ", ".join(f"{key}:{int(value)}" for key, value in sorted(source_breakdown.items()))
            taxonomy_notes.append(f"Source mix: {mix}")
        if discussion_source_count <= 0:
            taxonomy_notes.append("No issue, PR, review, or comment discussion sources were available; conflict detection may under-report because evidence is limited to commits.")
        elif discussion_source_count < 8:
            taxonomy_notes.append(f"Discussion coverage is low ({discussion_source_count} discussion sources), so conflict detection may miss weaker tensions.")
        if conflict_rows and not any(
            item.primary_link and str(item.primary_link.source_type or "") in self.DISCUSSION_SOURCE_TYPES
            for item in conflict_rows
        ):
            taxonomy_notes.append("Confirmed conflicts are backed without a primary issue/PR discussion link, so inspect traceability carefully because the evidence is mostly commit-level or indirect.")
        if not conflict_rows and potential_conflicts:
            taxonomy_notes.append(f"No confirmed conflicts were returned, but heuristic pre-scan found {len(potential_conflicts)} potentially tense threads with trace links.")
        if extra_notes:
            taxonomy_notes.extend([str(note).strip() for note in extra_notes if str(note).strip()])

        return TopicModelingResult(
            status="Completed",
            model=self.model,
            judge_model=judge_model,
            generated_at=datetime.now(),
            source_count=source_count,
            discussion_source_count=discussion_source_count,
            llm_run_count=max(1, int(llm_run_count or 1)),
            judged=bool(judged),
            source_breakdown=source_breakdown,
            taxonomy_notes=taxonomy_notes[:12],
            roles=role_rows,
            developers=developer_rows,
            conflicts=conflict_rows,
            potential_conflict_threads=potential_conflicts,
            error=None,
        )

    def _build_topics(self, raw_topics: List[Any], source_map: Dict[str, Dict[str, Any]]) -> List[TopicNode]:
        topics: List[TopicNode] = []
        for raw_topic in raw_topics:
            if not isinstance(raw_topic, dict):
                continue
            subtopics: List[TopicSubtopic] = []
            for raw_subtopic in (raw_topic.get("subtopics") or []):
                if not isinstance(raw_subtopic, dict):
                    continue
                trace_links = self._trace_links_from_ids(raw_subtopic.get("trace_source_ids") or [], source_map)
                evidence_count = len(trace_links) if trace_links else max(0, int(raw_subtopic.get("evidence_count") or 0))
                subtopics.append(
                    TopicSubtopic(
                        name=str(raw_subtopic.get("name") or "Unnamed subtopic").strip(),
                        summary=str(raw_subtopic.get("summary") or "").strip(),
                        evidence_count=evidence_count,
                        examples=[str(x).strip() for x in (raw_subtopic.get("examples") or []) if str(x).strip()][:3],
                        trace_links=trace_links,
                    )
                )
            topic_trace_links = self._trace_links_from_ids(raw_topic.get("trace_source_ids") or [], source_map)
            raw_topic_evidence = max(0, int(raw_topic.get("evidence_count") or 0))
            if subtopics:
                topic_evidence_count = sum(max(0, int(item.evidence_count or 0)) for item in subtopics)
            else:
                topic_evidence_count = len(topic_trace_links) if topic_trace_links else raw_topic_evidence
            topics.append(
                TopicNode(
                    name=str(raw_topic.get("name") or "Unnamed topic").strip(),
                    summary=str(raw_topic.get("summary") or "").strip(),
                    evidence_count=topic_evidence_count,
                    subtopics=subtopics,
                    trace_links=topic_trace_links,
                )
            )
        return topics

    def _trace_links_from_ids(self, source_ids: List[Any], source_map: Dict[str, Dict[str, Any]]) -> List[TraceabilityLink]:
        links: List[TraceabilityLink] = []
        seen = set()
        for raw_id in source_ids:
            source_id = str(raw_id or "").strip()
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            row = source_map.get(source_id)
            if not row:
                continue
            links.append(
                TraceabilityLink(
                    source_id=source_id,
                    label=str(row.get("label") or source_id),
                    url=str(row.get("url") or ""),
                    source_type=str(row.get("source_type") or ""),
                    is_open=bool(row.get("is_open")),
                )
            )
        return links[:8]

    def _normalize_conflict_participants(self, raw_conflict: Dict[str, Any], developer_id: str, counterpart_id: str) -> List[str]:
        participants: List[str] = []
        for raw_id in (raw_conflict.get("participant_ids") or []):
            participant_id = str(raw_id or "").strip()
            if participant_id and participant_id not in participants:
                participants.append(participant_id)
        for fallback_id in [developer_id, counterpart_id]:
            if fallback_id and fallback_id not in participants:
                participants.append(fallback_id)
        return participants

    def _normalize_conflict_roles(
        self,
        raw_conflict: Dict[str, Any],
        developer_id: str,
        counterpart_id: str,
        developer_role_map: Dict[str, str],
        participant_ids: Optional[List[str]] = None,
    ) -> List[str]:
        roles: List[str] = []
        normalized_from_payload = [
            self._normalize_role(item)
            for item in (raw_conflict.get("participant_roles") or [])
        ]
        for role in normalized_from_payload:
            if role in self.ROLE_ORDER and role not in roles:
                roles.append(role)
        if roles:
            return roles
        participant_id_list = participant_ids or self._normalize_conflict_participants(raw_conflict, developer_id, counterpart_id)
        for participant_id in participant_id_list:
            role = self._normalize_role(developer_role_map.get(participant_id))
            if role in self.ROLE_ORDER and role not in roles:
                roles.append(role)
        return roles

    def _conflict_role_combination(
        self,
        raw_conflict: Dict[str, Any],
        developer_id: str,
        counterpart_id: str,
        developer_role_map: Dict[str, str],
        participant_ids: Optional[List[str]] = None,
        participant_roles: Optional[List[str]] = None,
    ) -> str:
        explicit = str(raw_conflict.get("role_combination") or "").strip()
        if explicit:
            normalized = self._normalize_role_combination_label(explicit)
            if normalized:
                return normalized
        roles = list(participant_roles or []) or self._normalize_conflict_roles(
            raw_conflict,
            developer_id,
            counterpart_id,
            developer_role_map,
            participant_ids=participant_ids,
        )
        if not roles:
            return self._role_combination(
                developer_role_map.get(developer_id, "Unknown"),
                developer_role_map.get(counterpart_id, "Unknown"),
            )
        unique = sorted(set(roles), key=lambda item: self.ROLE_ORDER.index(item))
        if len(unique) == 1:
            return unique[0]
        return " x ".join(unique)

    def _normalize_role_combination_label(self, value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        parts = [self._normalize_role(item) for item in re.split(r"\s*x\s*", raw) if str(item).strip()]
        valid = [part for part in parts if part in self.ROLE_ORDER]
        if not valid:
            return ""
        unique = sorted(set(valid), key=lambda item: self.ROLE_ORDER.index(item))
        if len(unique) == 1:
            return unique[0]
        return " x ".join(unique)

    def _primary_trace_link(
        self,
        primary_source_id: str,
        source_ids: List[Any],
        source_map: Dict[str, Dict[str, Any]],
    ) -> Optional[TraceabilityLink]:
        primary_id = str(primary_source_id or "").strip()
        if primary_id and source_map.get(primary_id):
            candidates = [primary_id]
        else:
            candidates = [str(item or "").strip() for item in source_ids if str(item or "").strip()]
        links = self._trace_links_from_ids(candidates, source_map)
        if not links:
            return None
        ranked = sorted(
            links,
            key=lambda link: (
                self.TRACEABILITY_SOURCE_PRIORITY.get(str(link.source_type or "").strip(), 99),
                0 if link.url else 1,
                len(str(link.label or "")),
            ),
        )
        return ranked[0]

    def _raw_conflict_is_open(self, raw_conflict: Dict[str, Any], source_map: Dict[str, Dict[str, Any]]) -> bool:
        for source_id in (raw_conflict.get("trace_source_ids") or []):
            row = source_map.get(str(source_id or "").strip())
            if row and bool(row.get("is_open")):
                return True
        return False

    def _threads_by_id(self, prepared: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for raw_thread in (prepared.get("threads") or []):
            if not isinstance(raw_thread, dict):
                continue
            thread_id = str(raw_thread.get("thread_id") or "").strip()
            if thread_id:
                out[thread_id] = raw_thread
        return out

    def _thread_participants_from_trace_sources(
        self,
        raw_conflict: Dict[str, Any],
        source_map: Dict[str, Dict[str, Any]],
        thread_map: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        participant_ids: List[str] = []
        source_ids: List[str] = []
        primary_source_id = str(raw_conflict.get("primary_trace_source_id") or "").strip()
        if primary_source_id:
            source_ids.append(primary_source_id)
        for raw_id in (raw_conflict.get("trace_source_ids") or []):
            source_id = str(raw_id or "").strip()
            if source_id and source_id not in source_ids:
                source_ids.append(source_id)
        for source_id in source_ids:
            thread_id = ""
            source_row = source_map.get(source_id)
            if source_row:
                thread_id = str(source_row.get("thread_id") or "").strip()
            if not thread_id and source_id in thread_map:
                thread_id = source_id
            thread = thread_map.get(thread_id)
            if not thread:
                continue
            if str(thread.get("source_type") or "") not in self.DISCUSSION_SOURCE_TYPES:
                continue
            for participant in (thread.get("participants") or []):
                participant_id = str((participant or {}).get("developer_id") or "").strip()
                if participant_id and participant_id not in participant_ids:
                    participant_ids.append(participant_id)
        return participant_ids

    def _conflict_participants_with_thread_context(
        self,
        raw_conflict: Dict[str, Any],
        developer_id: str,
        counterpart_id: str,
        source_map: Dict[str, Dict[str, Any]],
        thread_map: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        participants = self._normalize_conflict_participants(raw_conflict, developer_id, counterpart_id)
        for participant_id in self._thread_participants_from_trace_sources(raw_conflict, source_map, thread_map):
            if participant_id not in participants:
                participants.append(participant_id)
        return participants

    def _collect_conflict_candidate_threads(self, threads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for thread in threads:
            raw_participants = thread.get("participants") or []
            if isinstance(raw_participants, dict):
                participants = [
                    {"developer_id": dev_id, "role": role}
                    for dev_id, role in sorted(raw_participants.items())
                ]
            else:
                participants = [item for item in raw_participants if isinstance(item, dict)]
            items = thread.get("items") or []
            if len(participants) < 2 or len(items) < 2:
                continue
            matched_signals: List[str] = []
            for item in items:
                text = str(item.get("text") or "")
                for label, pattern in self.CONFLICT_SIGNAL_PATTERNS:
                    if pattern.search(text) and label not in matched_signals:
                        matched_signals.append(label)
            if not matched_signals:
                continue
            participant_roles = [
                self._normalize_role(item.get("role"))
                for item in participants
                if self._normalize_role(item.get("role")) in self.ROLE_ORDER
            ]
            role_combination = self._normalize_role_combination_label(" x ".join(participant_roles))
            candidates.append({
                "thread_id": str(thread.get("thread_id") or ""),
                "thread_label": str(thread.get("thread_label") or ""),
                "thread_url": str(thread.get("thread_url") or ""),
                "source_type": str(thread.get("source_type") or ""),
                "is_open": bool(thread.get("is_open")),
                "participant_ids": [str(item.get("developer_id") or "") for item in participants if str(item.get("developer_id") or "").strip()],
                "participant_roles": participant_roles,
                "role_combination": role_combination,
                "matched_signals": matched_signals,
                "summary": (
                    f"{len(matched_signals)} tension signals across {len(items)} messages from {len(participants)} participants."
                    + (f" Community mix: {role_combination}." if role_combination else "")
                ),
                "trace_source_ids": [str(item.get("source_id") or "") for item in items[:6] if str(item.get("source_id") or "").strip()],
            })
        candidates.sort(
            key=lambda item: (
                0 if str(item.get("source_type") or "") in self.DISCUSSION_SOURCE_TYPES else 1,
                -len(item.get("matched_signals") or []),
                -len(item.get("participant_ids") or []),
                0 if item.get("is_open") else 1,
                str(item.get("thread_label") or ""),
            )
        )
        return candidates[:16]

    def _build_potential_conflicts(self, prepared: Dict[str, Any], source_map: Dict[str, Dict[str, Any]]) -> List[PotentialConflictThread]:
        rows: List[PotentialConflictThread] = []
        for item in (prepared.get("potential_conflict_threads") or []):
            if not isinstance(item, dict):
                continue
            rows.append(
                PotentialConflictThread(
                    thread_id=str(item.get("thread_id") or "").strip(),
                    thread_label=str(item.get("thread_label") or "").strip(),
                    thread_url=str(item.get("thread_url") or "").strip(),
                    source_type=str(item.get("source_type") or "").strip(),
                    is_open=bool(item.get("is_open")),
                    participant_ids=[str(x).strip() for x in (item.get("participant_ids") or []) if str(x).strip()],
                    participant_roles=[self._normalize_role(x) for x in (item.get("participant_roles") or []) if self._normalize_role(x) in self.ROLE_ORDER],
                    matched_signals=[str(x).strip() for x in (item.get("matched_signals") or []) if str(x).strip()],
                    summary=str(item.get("summary") or "").strip(),
                    source_links=self._trace_links_from_ids(item.get("trace_source_ids") or [], source_map),
                )
            )
        return rows

    def _normalize_role(self, value: Any) -> str:
        role = str(value or "").strip().lower()
        if "hybrid" in role:
            return "Hybrid"
        if "ai" in role or "ml" in role:
            return "AI/ML Engineer"
        if "software engineer" in role or role == "software" or re.search(r"\bse\b", role):
            return "Software Engineer"
        return "Unknown"

    def _role_combination(self, role_a: str, role_b: str) -> str:
        ordered = sorted([self._normalize_role(role_a), self._normalize_role(role_b)])
        if len(ordered) == 2 and ordered[0] == ordered[1]:
            return ordered[0]
        return " x ".join(ordered)

    def _clean_text(self, value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text[: self.max_text_len] if text else ""

    def _response_schema(self) -> Dict[str, Any]:
        topic_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string"},
                "summary": {"type": "string"},
                "evidence_count": {"type": "integer"},
                "trace_source_ids": {"type": "array", "items": {"type": "string"}},
                "subtopics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string"},
                            "summary": {"type": "string"},
                            "evidence_count": {"type": "integer"},
                            "examples": {"type": "array", "items": {"type": "string"}},
                            "trace_source_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["name", "summary", "evidence_count", "examples", "trace_source_ids"],
                    },
                },
            },
            "required": ["name", "summary", "evidence_count", "trace_source_ids", "subtopics"],
        }

        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "taxonomy_notes": {"type": "array", "items": {"type": "string"}},
                "roles": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "role": {"type": "string"},
                            "summary": {"type": "string"},
                            "topics": {"type": "array", "items": topic_schema},
                        },
                        "required": ["role", "summary", "topics"],
                    },
                },
                "developers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "developer_id": {"type": "string"},
                            "role": {"type": "string"},
                            "documents_count": {"type": "integer"},
                            "summary": {"type": "string"},
                            "trace_source_ids": {"type": "array", "items": {"type": "string"}},
                            "topics": {"type": "array", "items": topic_schema},
                        },
                        "required": ["developer_id", "role", "documents_count", "summary", "trace_source_ids", "topics"],
                    },
                },
                "conflicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "conflict_title": {"type": "string"},
                            "developer_id": {"type": "string"},
                            "counterpart_id": {"type": "string"},
                            "participant_ids": {"type": "array", "items": {"type": "string"}},
                            "participant_roles": {"type": "array", "items": {"type": "string"}},
                            "role_combination": {"type": "string"},
                            "status": {"type": "string"},
                            "summary": {"type": "string"},
                            "resolution_summary": {"type": "string"},
                            "evidence_count": {"type": "integer"},
                            "open_conflict": {"type": "boolean"},
                            "primary_trace_source_id": {"type": "string"},
                            "trace_source_ids": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": [
                            "conflict_title",
                            "developer_id",
                            "counterpart_id",
                            "participant_ids",
                            "participant_roles",
                            "role_combination",
                            "status",
                            "summary",
                            "resolution_summary",
                            "evidence_count",
                            "open_conflict",
                            "primary_trace_source_id",
                            "trace_source_ids",
                        ],
                    },
                },
            },
            "required": ["taxonomy_notes", "roles", "developers", "conflicts"],
        }
