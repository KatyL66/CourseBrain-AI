import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.request_context import request_id_ctx
from app.db.chroma_store import find_course_by_id
from app.models.schemas import (
    FinalSelectedChunkDebug,
    MergedCandidateDebug,
    PerQueryRetrievalDebug,
    QueryPlanDebug,
    RetrieveCandidateDebug,
    RetrieveDebugResponse,
    RetrieveRoutingDebug,
    SearchRequest,
    SearchResponse,
)
from app.services.query_intent import plan_query
from app.services.retrieval_router import FINAL_TOP_K, PlannedRetrievalResult, planned_retrieval

logger = logging.getLogger("coursebrain")

router = APIRouter(prefix="/api/v1", tags=["search"])


def _build_search_response(course_id: UUID, query: str, top_k: int, results) -> SearchResponse:
    course = find_course_by_id(course_id)
    collection = f"course_{course['id']}" if course else "unknown"
    return SearchResponse(
        course_id=course_id,
        query=query,
        embedding_model=settings.embedding_model,
        collection=collection,
        top_k=top_k,
        results=results,
    )


def _candidate_debug(rank: int, candidate, *, matched_queries: list[str] | None = None) -> RetrieveCandidateDebug:
    return RetrieveCandidateDebug(
        rank=rank,
        tier=candidate.tier,
        content_type=candidate.content_type,
        score=candidate.score,
        source=candidate.source_title,
        page=candidate.page,
        text=candidate.text,
        matched_queries=matched_queries or [],
    )


def _build_retrieve_debug_response(
    course_id: UUID,
    query: str,
    plan,
    planned: PlannedRetrievalResult,
    top_k: int,
) -> RetrieveDebugResponse:
    course = find_course_by_id(course_id)
    collection = f"course_{course['id']}" if course else "unknown"

    retrieval_per_query = []
    for search_query, routed in planned.per_query:
        cand_map = {c.chunk_id: c for c in routed.candidates}
        results = []
        for i, hit in enumerate(routed.final_results, start=1):
            c = cand_map.get(str(hit.chunk_id))
            if c:
                results.append(_candidate_debug(i, c))
        retrieval_per_query.append(PerQueryRetrievalDebug(search_query=search_query, results=results))

    merged_candidates = [
        MergedCandidateDebug(
            chunk_id=m.chunk_id,
            tier=m.tier,
            content_type=m.content_type,
            score=m.score,
            matched_queries=m.matched_queries,
            source=m.source_title,
            page=m.page,
            text=m.text,
        )
        for m in planned.merged_candidates
    ]

    final_selected = [
        FinalSelectedChunkDebug(
            rank=hit.rank,
            chunk_id=str(hit.chunk_id),
            tier=hit.routing_tier or "unknown",
            content_type=hit.source.content_type,
            score=hit.score,
            matched_queries=hit.matched_queries,
            source=hit.source.topic_title,
            page=hit.source.page,
            text=hit.text,
        )
        for hit in planned.final_results
    ]

    flat_candidates = [
        RetrieveCandidateDebug(
            rank=i,
            tier=c.tier,
            content_type=c.content_type,
            score=c.score,
            source=c.source_title,
            page=c.page,
            text=c.text,
            matched_queries=c.matched_queries,
        )
        for i, c in enumerate(planned.merged_candidates, start=1)
    ]

    routing = RetrieveRoutingDebug(
        intent=planned.routing.intent,
        intent_confidence=plan.confidence,
        primary_content_types=planned.routing.primary_content_types,
        secondary_content_types=planned.routing.secondary_content_types,
        fallback_content_types=planned.routing.fallback_content_types,
        tiers_searched=planned.routing.tiers_searched,
        enough_from_primary=planned.routing.enough_from_primary,
    )

    return RetrieveDebugResponse(
        question=query,
        query_plan=QueryPlanDebug(
            intent=plan.intent.value,
            intent_confidence=plan.confidence,
            topic=plan.topic,
            question_type=plan.question_type.value,
            search_queries=planned.search_queries,
        ),
        retrieval_per_query=retrieval_per_query,
        merged_candidates=merged_candidates,
        final_selected=final_selected,
        intent=plan.intent.value,
        intent_confidence=plan.confidence,
        routing=routing,
        candidates=flat_candidates,
        final_top_k=planned.final_results,
        embedding_model=settings.embedding_model,
        collection=collection,
    )


@router.get("/debug/retrieve", response_model=RetrieveDebugResponse)
async def debug_retrieve(
    course_id: UUID = Query(..., description="Internal course UUID"),
    q: str = Query(..., min_length=1, description="User question"),
    top_k: int = Query(5, ge=1, le=20),
):
    """Routed retrieval debug: query plan, per-query hits, merge, final selection."""
    logger.info(
        "retrieve debug request_id=%s course_id=%s q=%s",
        request_id_ctx.get(),
        course_id,
        q[:200],
    )
    if not find_course_by_id(course_id):
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        plan = await plan_query(q)
        planned = await planned_retrieval(
            course_id,
            q,
            plan,
            final_top_k=min(top_k, FINAL_TOP_K),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _build_retrieve_debug_response(course_id, q, plan, planned, top_k)


@router.post("/search", response_model=SearchResponse)
async def search_endpoint(payload: SearchRequest):
    if not find_course_by_id(payload.course_id):
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        plan = await plan_query(payload.query)
        planned = await planned_retrieval(
            payload.course_id,
            payload.query,
            plan,
            final_top_k=min(payload.top_k, FINAL_TOP_K),
        )
        results = planned.final_results
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _build_search_response(payload.course_id, payload.query, payload.top_k, results)
