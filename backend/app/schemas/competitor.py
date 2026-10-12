from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CompetitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    website_url: Optional[str] = Field(default=None, max_length=1024)
    description: Optional[str] = Field(default=None, max_length=5000)
    notes: Optional[str] = Field(default=None, max_length=20000)


class CompetitorUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    website_url: Optional[str] = Field(default=None, max_length=1024)
    description: Optional[str] = Field(default=None, max_length=5000)
    notes: Optional[str] = Field(default=None, max_length=20000)


class EvidenceResponse(BaseModel):
    id: UUID
    evidence_type: str
    source_url: Optional[str] = None
    title: Optional[str] = None
    status: str
    error: Optional[str] = None
    excerpt: Optional[str] = None
    char_count: int = 0
    created_at: Optional[datetime] = None


class CompetitorResponse(BaseModel):
    id: UUID
    name: str
    website_url: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    origin: str
    suggestion_reason: Optional[str] = None
    # user_added | named_in_sources | unverified (AI candidate without evidence) | evidence_backed
    verification: str
    analysis_status: str
    analysis: Optional[Dict[str, Any]] = None
    analysis_error: Optional[str] = None
    last_analyzed_at: Optional[datetime] = None
    evidence: List[EvidenceResponse] = []


class CompetitorAnalysisResponse(BaseModel):
    product_id: UUID
    product_name: str
    product_profile_approved: bool
    product_summary: Dict[str, Any] = {}
    status: str  # locked | not_started | in_progress | ready_for_review | approved
    version: int
    approved_version: Optional[int] = None
    approved_at: Optional[datetime] = None
    limited_evidence: bool = False  # approved without full competitor evidence
    comparison: Optional[Dict[str, Any]] = None
    comparison_outdated: bool = False
    comparison_at: Optional[datetime] = None
    competitors: List[CompetitorResponse] = []


class DiscoverResponse(BaseModel):
    added: List[str]
    messages: List[str]
    state: CompetitorAnalysisResponse


class ApproveCompetitorAnalysisRequest(BaseModel):
    project_id: UUID
    version: int
    # Explicitly accept a limited-evidence state (no analyzed competitor / no current comparison).
    limited_evidence: bool = False


class SignalArticleItem(BaseModel):
    title: str
    source_url: str
    domain: str
    published_at: Optional[str] = None
    retrieved_at: str
    matching_query: str
    language: Optional[str] = None
    source_country: Optional[str] = None


class SignalSearchResponse(BaseModel):
    status: str
    articles: List[SignalArticleItem] = []
    evidence_evaluation: Dict[str, str] = {}
    matching_query: str
    total_found: int = 0
    error_message: Optional[str] = None
    retry_after: Optional[int] = None
    cached: Optional[bool] = None


class IngestSignalRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    source_url: str = Field(min_length=1, max_length=1024)
    domain: Optional[str] = Field(default=None, max_length=255)
    published_at: Optional[str] = None
    matching_query: Optional[str] = None
    limitations: Optional[str] = None


class RedditPostItem(BaseModel):
    title: str
    source_url: str
    subreddit: str
    published_at: Optional[str] = None
    retrieved_at: str
    matching_query: str
    excerpt: str
    score: int = 0
    num_comments: int = 0


class UGCSearchResponse(BaseModel):
    status: str
    posts: List[RedditPostItem] = []
    matching_query: str
    total_found: int = 0
    error_message: Optional[str] = None
    limitations: Optional[str] = None


class IngestUGCRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    source_url: str = Field(min_length=1, max_length=1024)
    subreddit: Optional[str] = Field(default=None, max_length=100)
    published_at: Optional[str] = None
    matching_query: Optional[str] = None
    excerpt: Optional[str] = None
    score: Optional[int] = 0
    num_comments: Optional[int] = 0
