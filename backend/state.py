"""Pydantic data models shared by every agent and the API (CLAUDE.md section 8)."""
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Method = Literal["classical", "llm_openai", "llm_claude", "ocr_tesseract",
                 "derived_from_filing", "fixture", "human", "none"]
UnitType = Literal["currency_per_share", "share_ratio", "percent", "amount", "count", "date", "text", "flag"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Evidence(BaseModel):
    """Where a value came from. page is 1-based; bbox is [x0, y0, x1, y1] in PDF points."""
    doc_id: Optional[str] = None
    page: Optional[int] = None
    bbox: Optional[list[float]] = None
    text: str = ""
    source_url: Optional[str] = None


class FieldValue(BaseModel):
    name: str
    value: Any = None
    unit: str = ""
    unit_type: UnitType = "text"
    confidence: float = 0.0
    method: Method = "classical"
    evidence: Evidence = Field(default_factory=Evidence)
    derived_from: list[str] = []    # names of fields this value was computed from (empty = read directly)


class RuleResult(BaseModel):
    rule_id: str
    status: Literal["pass", "fail", "not_applicable"]
    passed: Optional[bool]          # None when not_applicable
    severity: Literal["critical", "warning", "info"]
    message: str
    expected: Any = None
    actual: Any = None
    source_clause: str = ""
    verify: bool = False            # clause text not yet confirmed against the PDF
    fields: list[str] = []          # fields the rule looked at (used by the resolver)


class Track(BaseModel):
    """One entity's figures inside a document (e.g. 'unconsolidated' vs 'consolidated')."""
    track_id: str
    entity_label: str
    pages: list[int] = []
    fields: list[FieldValue] = []
    rule_results: list[RuleResult] = []
    status: str = "pending"

    def get(self, name: str) -> Optional[FieldValue]:
        return next((f for f in self.fields if f.name == name), None)

    def value(self, name: str) -> Any:
        f = self.get(name)
        return f.value if f else None

    def put(self, field: FieldValue) -> None:
        """Insert or replace a field by name."""
        self.fields = [f for f in self.fields if f.name != field.name] + [field]


class AuditEvent(BaseModel):
    batch_id: Optional[str] = None
    doc_id: str
    track_id: Optional[str] = None
    stage: str
    agent: str
    method: Method = "classical"
    decision: str = ""
    confidence: Optional[float] = None
    rule_ids: list[str] = []
    evidence: Optional[Evidence] = None
    started_at: str = Field(default_factory=now_iso)
    duration_ms: float = 0.0
    status: str = "ok"              # ok | warning | error


class Document(BaseModel):
    doc_id: str                     # unique key in this system (e.g. JOB-00012, PSX-282260)
    external_id: str = ""           # the ID the source uses (e.g. FDOC-35032) — used for dedup
    source: Literal["csv_ps01", "csv_ps07", "manifest", "fixture", "upload"]
    filename: str
    path: Optional[str] = None      # local PDF path, if there is a file
    sha256: Optional[str] = None
    metadata: dict = {}             # normalised intake row
    doc_type: Optional[str] = None
    doc_type_confidence: float = 0.0
    relevance: Optional[bool] = None
    stream: Optional[str] = None
    legacy_stream: Optional[str] = None
    company: Optional[FieldValue] = None
    symbol: Optional[str] = None
    period: Optional[FieldValue] = None
    pages: int = 0
    page_methods: dict[int, str] = {}   # page -> how its text was read (text_layer/ocr_tesseract/llm_*/unread)
    tracks: list[Track] = []
    duplicate_of: Optional[str] = None
    duplicate_reason: str = ""
    complexity: list[str] = []      # complexity triggers that fired
    escalation_reasons: list[str] = []
    route: Optional[str] = None     # auto_approve | needs_review | archive | reject | duplicate
    review_packet: Optional[dict] = None
    status: str = "queued"
    label: Optional[str] = None     # e.g. "Reconstruction from public reporting"
    resolver_loops: int = 0
    timings: dict[str, float] = {}  # stage -> ms
    batch_id: Optional[str] = None
