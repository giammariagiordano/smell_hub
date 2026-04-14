from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from datetime import datetime

class TraceabilityLink(BaseModel):
    source_id: str
    label: str = ""
    url: str = ""
    source_type: str = ""
    is_open: bool = False


class TopicSubtopic(BaseModel):
    name: str
    summary: str = ""
    evidence_count: int = 0
    examples: List[str] = Field(default_factory=list)
    trace_links: List[TraceabilityLink] = Field(default_factory=list)


class TopicNode(BaseModel):
    name: str
    summary: str = ""
    evidence_count: int = 0
    subtopics: List[TopicSubtopic] = Field(default_factory=list)
    trace_links: List[TraceabilityLink] = Field(default_factory=list)


class RoleTopicTree(BaseModel):
    role: str
    summary: str = ""
    documents_count: int = 0
    topics: List[TopicNode] = Field(default_factory=list)


class DeveloperTopicProfile(BaseModel):
    developer_id: str
    role: str = "Unknown"
    documents_count: int = 0
    summary: str = ""
    topics: List[TopicNode] = Field(default_factory=list)
    trace_links: List[TraceabilityLink] = Field(default_factory=list)


class DeveloperConflictRecord(BaseModel):
    conflict_title: str = ""
    developer_id: str
    developer_role: str = "Unknown"
    counterpart_id: str
    counterpart_role: str = "Unknown"
    participant_ids: List[str] = Field(default_factory=list)
    participant_roles: List[str] = Field(default_factory=list)
    role_combination: str = ""
    status: str = "unknown"
    summary: str = ""
    resolution_summary: str = ""
    evidence_count: int = 0
    open_conflict: bool = False
    primary_link: Optional[TraceabilityLink] = None
    source_links: List[TraceabilityLink] = Field(default_factory=list)


class PotentialConflictThread(BaseModel):
    thread_id: str
    thread_label: str = ""
    thread_url: str = ""
    source_type: str = ""
    is_open: bool = False
    participant_ids: List[str] = Field(default_factory=list)
    participant_roles: List[str] = Field(default_factory=list)
    matched_signals: List[str] = Field(default_factory=list)
    summary: str = ""
    source_links: List[TraceabilityLink] = Field(default_factory=list)


class TopicModelingResult(BaseModel):
    status: str = "Not analyzed"
    model: str = ""
    judge_model: str = ""
    generated_at: Optional[datetime] = None
    source_count: int = 0
    discussion_source_count: int = 0
    llm_run_count: int = 1
    judged: bool = False
    source_breakdown: Dict[str, int] = Field(default_factory=dict)
    taxonomy_notes: List[str] = Field(default_factory=list)
    roles: List[RoleTopicTree] = Field(default_factory=list)
    developers: List[DeveloperTopicProfile] = Field(default_factory=list)
    conflicts: List[DeveloperConflictRecord] = Field(default_factory=list)
    potential_conflict_threads: List[PotentialConflictThread] = Field(default_factory=list)
    error: Optional[str] = None


class LLMSettingsResponse(BaseModel):
    provider: str = "OpenAI"
    model: str = "gpt-5-mini"
    llm_runs: int = 1
    organization: str = ""
    project: str = ""
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    has_api_key: bool = False
    api_key_masked: str = ""
    has_github_token: bool = False
    github_token_masked: str = ""


class LLMSettingsUpdateRequest(BaseModel):
    model: Optional[str] = None
    llm_runs: Optional[int] = None
    organization: Optional[str] = None
    project: Optional[str] = None
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    github_token: Optional[str] = None
    clear_api_key: bool = False
    clear_github_token: bool = False


class Developer(BaseModel):
    id: str  # Unique person ID after identity matching
    aliases: List[str] = []
    emails: List[str] = []
    classification: str = "Unknown"  # SE, AI, Hybrid
    gender: str = "Unknown"  # Woman, Man, Non-binary, Multi-pronoun, No-pronoun, Unknown
    gender_confidence: float = 0.0
    gender_source: str = "none"  # e.g. github_bio_pronouns
    pronouns_detected: List[str] = []
    se_score: float = 0.0
    ai_score: float = 0.0
    ml_score: float = 0.0
    community_smells: List[str] = []  # Community smell IDs affecting this dev
    ml_smells: List[str] = []         # ML-specific smell IDs in files this dev authored
    ml_smell_details: List[Dict[str, Any]] = [] # Rich details about authored smells
    traditional_smells: List[str] = []  # Traditional code smell IDs introduced by this dev
    traditional_smell_details: List[Dict[str, Any]] = []  # Details for traditional smells
    vulnerabilities: List[str] = []  # Vulnerability test IDs (Bandit) attributed to this dev
    vulnerability_details: List[Dict[str, Any]] = []  # Detailed vulnerability instances
    bug_introduced_count: int = 0  # Number of bug-inducing commits attributed by R-SZZ
    commits_count: int = 0
    bug_fix_commits_count: int = 0
    files_touched_count: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    code_churn: int = 0
    avg_files_per_commit: float = 0.0
    sentiment_score: float = 0.0
    sentiment_label: str = "Unknown"
    sentiment_messages_count: int = 0
    sentiment_emotions: Dict[str, float] = {}
    is_abandoned: bool = False
    abandonment_status: str = "Active"  # Active, Abandoned
    last_interaction_window_id: Optional[str] = None
    last_interaction_window_label: Optional[str] = None
    abandoned_since_window_id: Optional[str] = None
    abandoned_since_window_label: Optional[str] = None
    abandoned_since_date: Optional[datetime] = None
    last_commit_hash: Optional[str] = None
    last_commit_date: Optional[datetime] = None
    last_commit_message: Optional[str] = None
    last_message_before_abandonment_hash: Optional[str] = None
    last_message_before_abandonment_date: Optional[datetime] = None
    last_message_before_abandonment: Optional[str] = None

class Commit(BaseModel):
    hash: str
    author_id: str
    date: datetime
    tz_offset_minutes: Optional[int] = None
    message: str
    files_modified: List[str] = []
    is_bug_fix: bool = False
    bug_id: Optional[str] = None
    is_bug_inducing: bool = False
    lines_added: int = 0
    lines_deleted: int = 0

class SmellInstance(BaseModel):
    smell_id: str
    name: str
    type: str  # Community, ML, Code
    description: str
    affected_entities: List[str]  # Developers or Files
    file_path: Optional[str] = None
    line: Optional[int] = None
    message: str
    evidence: Dict[str, Any] = {}
    time_window: Optional[str] = None
    snippet: Optional[str] = None
    refactoring_suggestion: Optional[str] = None

class VulnerabilityInstance(BaseModel):
    vuln_id: str
    name: str
    type: str  # Vulnerability
    severity: str
    confidence: str
    description: str
    affected_entities: List[str]
    file_path: Optional[str] = None
    line: Optional[int] = None
    message: str
    cwe: Optional[str] = None
    tool: str = "Bandit"

class ProjectMetrics(BaseModel):
    project_id: str
    time_window: Optional[str] = None
    cbo: float = 0.0
    dit: float = 0.0
    lcom: float = 0.0
    loc: int = 0
    noc: int = 0
    nom: int = 0
    rfc: float = 0.0
    wmc: float = 0.0
    community_smells_count: Dict[str, int] = {}
    community_smell_instances: List[Dict[str, Any]] = []
    ml_smells_count: Dict[str, int] = {}
    traditional_smells_count: Dict[str, int] = {}
    vulnerabilities_count: Dict[str, int] = {}
    vulnerabilities_severity_count: Dict[str, int] = {}
    table3_metrics: Dict[str, Any] = {}
    abandoned_developers_count: int = 0
    abandoned_developers_ids: List[str] = []

class ProjectTimeWindow(BaseModel):
    id: str
    label: str
    start_date: datetime
    end_date: datetime
    developers: List[Developer] = []
    metrics: ProjectMetrics
    collaboration_edges: List[Dict[str, Any]] = []

class Project(BaseModel):
    id: str
    name: str
    url: str
    local_path: str
    last_analyzed: Optional[datetime] = None
    analysis_status: str = "None"  # None, Running, Completed, Error
    analysis_progress_pct: float = 0.0
    analysis_eta_seconds: Optional[int] = None
    analysis_window_index: int = 0
    analysis_window_total: int = 0
    last_analysis_duration_seconds: Optional[float] = None
    last_analysis_window_count: Optional[int] = None
    ml_detection_status: str = "Unknown"
    ml_detection_error: Optional[str] = None
    ml_detection_stdout: Optional[str] = None
    ml_detection_stderr: Optional[str] = None
    developers: List[Developer] = []
    metrics: List[ProjectMetrics] = []
    collaboration_edges: List[Dict[str, Any]] = [] # [{from, to, weight}]
    time_windows: List[ProjectTimeWindow] = []
    active_time_window_id: Optional[str] = None
    ml_call_graph_nodes: List[Dict[str, Any]] = []
    ml_call_graph_edges: List[Dict[str, Any]] = []
    topic_modeling: TopicModelingResult = Field(default_factory=TopicModelingResult)
