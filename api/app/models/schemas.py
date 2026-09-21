from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SourceMetadata(BaseModel):
    platform: str = "brightspace"
    course_id: str
    course_code: str | None = None
    module: str | None = None
    content_type: str | None = None
    topic_id: str
    topic_title: str
    url: str
    file_type: str | None = None
    page: int | None = None
    anchor_text: str | None = None
    source_type: str | None = None


class TopicIngest(BaseModel):
    external_id: str
    module_name: str | None = None
    title: str
    url: str
    file_type: str | None = None
    topic_type: int | None = None
    content: str | None = None  # plain text or HTML text
    content_base64: str | None = None  # PDF binary as base64


class AssignmentAttachmentIngest(BaseModel):
    filename: str
    file_type: str | None = None
    content: str | None = None
    content_base64: str | None = None


class AssignmentIngest(BaseModel):
    object_id: str
    name: str
    canonical_url: str
    due_at: str | None = None
    submission_type: str | None = None
    instructions: str | None = None
    attachments: list[AssignmentAttachmentIngest] = Field(default_factory=list)


class IngestBatchRequest(BaseModel):
    external_id: str
    name: str
    platform: str = "brightspace"
    topics: list[TopicIngest] = Field(default_factory=list)
    assignments: list[AssignmentIngest] = Field(default_factory=list)


class IngestBatchResponse(BaseModel):
    course_id: UUID
    indexed_topics: int
    total_chunks: int
    skipped: list[str] = Field(default_factory=list)
    indexed_assignments: int = 0


class SearchRequest(BaseModel):
    course_id: UUID
    query: str
    top_k: int = 5


class SearchResult(BaseModel):
    chunk_id: UUID
    rank: int
    text: str
    score: float  # cosine similarity (1 - distance)
    distance: float  # raw cosine distance from Chroma
    source: SourceMetadata
    matched_queries: list[str] = Field(default_factory=list)
    routing_tier: str | None = None


class RetrieveCandidateDebug(BaseModel):
    rank: int
    tier: str
    content_type: str | None
    score: float
    source: str
    page: int | None
    text: str
    matched_queries: list[str] = Field(default_factory=list)


class QueryPlanDebug(BaseModel):
    intent: str
    intent_confidence: float | None = None
    topic: str | None = None
    question_type: str | None = None
    search_queries: list[str] = Field(default_factory=list)


class PerQueryRetrievalDebug(BaseModel):
    search_query: str
    results: list[RetrieveCandidateDebug] = Field(default_factory=list)


class MergedCandidateDebug(BaseModel):
    chunk_id: str
    tier: str
    content_type: str | None
    score: float
    matched_queries: list[str] = Field(default_factory=list)
    source: str
    page: int | None
    text: str


class FinalSelectedChunkDebug(BaseModel):
    rank: int
    chunk_id: str
    tier: str
    content_type: str | None
    score: float
    matched_queries: list[str] = Field(default_factory=list)
    source: str
    page: int | None
    text: str


class RetrieveRoutingDebug(BaseModel):
    intent: str
    intent_confidence: float | None = None
    primary_content_types: list[str]
    secondary_content_types: list[str]
    fallback_content_types: list[str]
    tiers_searched: list[str]
    enough_from_primary: bool


class RetrieveDebugResponse(BaseModel):
    question: str
    query_plan: QueryPlanDebug | None = None
    retrieval_per_query: list[PerQueryRetrievalDebug] = Field(default_factory=list)
    merged_candidates: list[MergedCandidateDebug] = Field(default_factory=list)
    final_selected: list[FinalSelectedChunkDebug] = Field(default_factory=list)
    intent: str
    intent_confidence: float | None = None
    routing: RetrieveRoutingDebug
    candidates: list[RetrieveCandidateDebug]
    final_top_k: list[SearchResult]
    embedding_model: str
    collection: str


class SearchResponse(BaseModel):
    course_id: UUID
    query: str
    embedding_model: str
    collection: str
    top_k: int
    results: list[SearchResult]


class ChatRequest(BaseModel):
    course_id: UUID
    message: str


class Citation(BaseModel):
    rank: int | None = None
    score: float | None = None
    topic_title: str
    module: str | None
    page: int | None
    url: str
    excerpt: str


class SourceReference(BaseModel):
    """Structured source for frontend clickable references (backend-controlled, not LLM-generated)."""

    id: str
    rank: int
    title: str
    module: str | None = None
    page: int | None = None
    url: str
    content_type: str | None = None
    label: str
    excerpt: str = ""


class RagDebugInfo(BaseModel):
    question: str
    query_intent: str | None = None
    query_intent_confidence: float | None = None
    question_type: str | None = None
    topic: str | None = None
    search_queries: list[str] = Field(default_factory=list)
    retrieval: list[SearchResult]
    rag_context: str
    messages: list[dict[str, str]]
    model: str


class ChatResponse(BaseModel):
    answer: str
    query_intent: str | None = None
    query_intent_confidence: float | None = None
    references: list[SourceReference] = Field(default_factory=list)
    referenced: list[Citation] = Field(default_factory=list)
    retrieved: list[Citation] = Field(default_factory=list)
    debug: RagDebugInfo | None = None


class CourseResponse(BaseModel):
    id: UUID
    external_id: str
    name: str
    platform: str
    topic_count: int
    chunk_count: int
    created_at: datetime


class CourseListResponse(BaseModel):
    courses: list[CourseResponse]
