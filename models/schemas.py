from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from datetime import datetime

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
