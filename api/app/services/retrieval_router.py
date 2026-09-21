"""Metadata-aware retrieval routing: intent → content_type tiers → Top-K."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from app.db.chroma_store import query_chunks
from app.models.schemas import SearchResult
from app.services.identifier_match import (
    collect_query_identifiers,
    extract_identifiers,
    identifier_boost,
)
from app.services.query_intent import QueryIntent, QueryIntentResult, is_course_wide_policy_question
from app.services.resource_resolver import (
    EvidenceScope,
    ResourceMatch,
    resolve_course_resources,
    unique_high_confidence_match,
)

# Informational for most intents. COURSE_INFO uses these to stop after syllabus/announcement.
MIN_USEFUL_SCORE = 0.30
ENOUGH_HIT_COUNT = 3
ENOUGH_TOP_SCORE = 0.40
CANDIDATE_POOL = 10
PER_QUERY_TOP_K = 5
MERGE_POOL_PER_QUERY = 8
SCOPED_CANDIDATE_POOL = 8
FINAL_TOP_K = 8

# Light source-priority prior on cosine-similarity scale. Relevance dominates; tier breaks near-ties.
TIER_PRIOR: dict[int, float] = {
    0: 0.02,  # primary
    1: 0.01,  # secondary
    2: 0.0,   # fallback
    3: 0.0,   # unfiltered
}

# COURSE_INFO: Overview/syllabus should beat a slightly higher-scoring assignment PDF.
COURSE_INFO_CONTENT_PRIOR: dict[str, float] = {
    "syllabus": 0.08,
    "announcement": 0.03,
}

ALL_CONTENT_TYPES = ["syllabus", "lecture", "assignment", "announcement", "other"]

# Intent determines source *priority*, not eligibility. Every type can appear in results.
PRIMARY_TIER_SIZE = 2
SECONDARY_TIER_SIZE = 2

INTENT_SOURCE_PRIORITY: dict[QueryIntent, list[str]] = {
    QueryIntent.COURSE_INFO: ["syllabus", "announcement", "lecture", "other", "assignment"],
    QueryIntent.LEARNING: ["lecture", "syllabus", "assignment", "other", "announcement"],
    QueryIntent.ASSIGNMENT: ["assignment", "announcement", "lecture", "syllabus", "other"],
    QueryIntent.MIXED: ALL_CONTENT_TYPES,
}


def _policy_from_priority(priority: list[str]) -> dict[str, list[str]]:
    """Split an ordered priority list into primary / secondary / fallback tiers."""
    primary = priority[:PRIMARY_TIER_SIZE]
    secondary = priority[PRIMARY_TIER_SIZE:PRIMARY_TIER_SIZE + SECONDARY_TIER_SIZE]
    fallback = priority[PRIMARY_TIER_SIZE + SECONDARY_TIER_SIZE:]
    covered = set(primary + secondary + fallback)
    for content_type in ALL_CONTENT_TYPES:
        if content_type not in covered:
            fallback.append(content_type)
    return {"primary": primary, "secondary": secondary, "fallback": fallback}


ROUTING_POLICY: dict[QueryIntent, dict[str, list[str]]] = {
    intent: _policy_from_priority(priority)
    for intent, priority in INTENT_SOURCE_PRIORITY.items()
}


@dataclass
class RoutingInfo:
    intent: str
    primary_content_types: list[str]
    secondary_content_types: list[str]
    fallback_content_types: list[str]
    tiers_searched: list[str] = field(default_factory=list)
    enough_from_primary: bool = False


@dataclass
class RoutedCandidate:
    chunk_id: str
    tier: str
    tier_rank: int
    content_type: str | None
    score: float
    source_title: str
    page: int | None
    text: str
    result: SearchResult


@dataclass
class RoutedRetrievalResult:
    routing: RoutingInfo
    candidates: list[RoutedCandidate]
    final_results: list[SearchResult]


@dataclass
class MergedCandidate:
    chunk_id: str
    tier: str
    tier_rank: int
    content_type: str | None
    score: float
    source_title: str
    page: int | None
    text: str
    result: SearchResult
    matched_queries: list[str] = field(default_factory=list)


@dataclass
class PlannedRetrievalResult:
    routing: RoutingInfo
    search_queries: list[str]
    per_query: list[tuple[str, RoutedRetrievalResult]]
    merged_candidates: list[MergedCandidate]
    final_results: list[SearchResult]
    resource_matches: list[ResourceMatch] = field(default_factory=list)
    evidence_scope: str | None = None


def _resource_priority_slots(final_top_k: int) -> int:
    """Reserved slots for scoped resource content when user names a unique resource."""
    if final_top_k <= 3:
        return max(1, final_top_k - 1)
    return min(final_top_k - 2, max(4, (final_top_k * 2) // 3))


def _enough_hits(hits: list[SearchResult]) -> bool:
    """True when a tier already has useful coverage. COURSE_INFO uses this as a cutoff."""
    if not hits:
        return False
    useful = [h for h in hits if h.score >= MIN_USEFUL_SCORE]
    if len(useful) >= ENOUGH_HIT_COUNT:
        return True
    return hits[0].score >= ENOUGH_TOP_SCORE


def _to_candidate(hit: SearchResult, tier: str, tier_rank: int) -> RoutedCandidate:
    return RoutedCandidate(
        chunk_id=str(hit.chunk_id),
        tier=tier,
        tier_rank=tier_rank,
        content_type=hit.source.content_type,
        score=hit.score,
        source_title=hit.source.topic_title,
        page=hit.source.page,
        text=hit.text,
        result=hit,
    )


def _to_merged_candidate(
    rc: RoutedCandidate,
    *,
    search_query: str | None = None,
) -> MergedCandidate:
    matched = [search_query] if search_query else []
    return MergedCandidate(
        chunk_id=rc.chunk_id,
        tier=rc.tier,
        tier_rank=rc.tier_rank,
        content_type=rc.content_type,
        score=rc.score,
        source_title=rc.source_title,
        page=rc.page,
        text=rc.text,
        result=rc.result,
        matched_queries=matched,
    )


def _rank_score(
    score: float,
    tier_rank: int,
    identifier_boost: float = 0.0,
    *,
    content_type: str | None = None,
    intent: QueryIntent | None = None,
) -> float:
    """Relevance-first score with light source-priority and identifier-match priors."""
    prior = TIER_PRIOR.get(tier_rank, 0.0) + identifier_boost
    if intent == QueryIntent.COURSE_INFO:
        prior += COURSE_INFO_CONTENT_PRIOR.get(content_type or "", 0.0)
    return score + prior


def _candidate_rank_key(
    candidate: RoutedCandidate | MergedCandidate,
    query_identifiers: list,
    intent: QueryIntent | None = None,
) -> tuple[float, int, int]:
    """Sort key: rank score (desc), then tier (asc), then matched query count (desc)."""
    boost = identifier_boost(candidate.text, query_identifiers)
    matched = len(getattr(candidate, "matched_queries", []) or [])
    return (
        -_rank_score(
            candidate.score,
            candidate.tier_rank,
            boost,
            content_type=candidate.content_type,
            intent=intent,
        ),
        candidate.tier_rank,
        -matched,
    )


def _dedupe_keep_best(candidates: list[RoutedCandidate]) -> list[RoutedCandidate]:
    """When the same chunk appears in multiple tiers, keep the highest-scoring instance."""
    best: dict[str, RoutedCandidate] = {}
    for c in candidates:
        existing = best.get(c.chunk_id)
        if existing is None or c.score > existing.score:
            best[c.chunk_id] = c
        elif c.score == existing.score and c.tier_rank < existing.tier_rank:
            best[c.chunk_id] = c
    return list(best.values())


def _rank_candidates(
    candidates: list[RoutedCandidate],
    query_identifiers: list,
    intent: QueryIntent | None = None,
) -> list[RoutedCandidate]:
    """Order by relevance first; source tier and identifier match are light priors."""
    return sorted(
        candidates,
        key=lambda c: _candidate_rank_key(c, query_identifiers, intent),
    )


def _exclude_dropbox_objects(candidates: list[RoutedCandidate]) -> list[RoutedCandidate]:
    """Dropbox objects only enter RAG via the named-assignment path, never general Top-K."""
    return [
        candidate
        for candidate in candidates
        if candidate.result.source.source_type != "assignment"
    ]


def _assign_ranks(hits: list[SearchResult]) -> list[SearchResult]:
    ranked: list[SearchResult] = []
    for i, hit in enumerate(hits, start=1):
        ranked.append(hit.model_copy(update={"rank": i}))
    return ranked


async def _search_tier(
    course_id: UUID,
    query: str,
    content_types: list[str] | None,
    tier: str,
    tier_rank: int,
) -> list[RoutedCandidate]:
    hits = await query_chunks(course_id, query, content_types, n_results=CANDIDATE_POOL)
    return [_to_candidate(h, tier, tier_rank) for h in hits]


async def routed_search(
    course_id: UUID,
    query: str,
    intent: QueryIntent,
    top_k: int = 5,
) -> RoutedRetrievalResult:
    policy = ROUTING_POLICY[intent]
    routing = RoutingInfo(
        intent=intent.value,
        primary_content_types=policy["primary"],
        secondary_content_types=policy["secondary"],
        fallback_content_types=policy["fallback"],
    )

    all_candidates: list[RoutedCandidate] = []

    if intent == QueryIntent.MIXED:
        routing.tiers_searched.append("all")
        hits = await query_chunks(course_id, query, None, n_results=CANDIDATE_POOL)
        all_candidates = [_to_candidate(h, "all", 0) for h in hits]
        query_ids = extract_identifiers(query)
        deduped = _rank_candidates(
            _dedupe_keep_best(_exclude_dropbox_objects(all_candidates)),
            query_ids,
            intent,
        )
        final = _assign_ranks([c.result for c in deduped[:top_k]])
        return RoutedRetrievalResult(routing=routing, candidates=deduped, final_results=final)

    skip_assignment_fallback = is_course_wide_policy_question(query)

    primary = await _search_tier(course_id, query, policy["primary"], "primary", 0)
    routing.tiers_searched.append("primary")
    all_candidates.extend(primary)
    routing.enough_from_primary = _enough_hits([c.result for c in primary])

    search_deeper = True
    if intent == QueryIntent.COURSE_INFO and routing.enough_from_primary:
        search_deeper = False

    if search_deeper and policy["secondary"]:
        secondary = await _search_tier(
            course_id, query, policy["secondary"], "secondary", 1,
        )
        routing.tiers_searched.append("secondary")
        all_candidates.extend(secondary)

    fallback_types = list(policy["fallback"])
    if skip_assignment_fallback:
        fallback_types = [t for t in fallback_types if t != "assignment"]
    if search_deeper and fallback_types:
        fallback = await _search_tier(
            course_id, query, fallback_types, "fallback", 2,
        )
        routing.tiers_searched.append("fallback")
        all_candidates.extend(fallback)

    if not all_candidates and not skip_assignment_fallback:
        routing.tiers_searched.append("unfiltered")
        hits = await query_chunks(course_id, query, None, n_results=CANDIDATE_POOL)
        all_candidates = [_to_candidate(h, "unfiltered", 3) for h in hits]

    all_candidates = _exclude_dropbox_objects(all_candidates)

    query_ids = extract_identifiers(query)
    deduped = _dedupe_keep_best(all_candidates)
    ranked = _rank_candidates(deduped, query_ids, intent)
    final = _assign_ranks([c.result for c in ranked[:top_k]])

    return RoutedRetrievalResult(
        routing=routing,
        candidates=ranked,
        final_results=final,
    )


def _candidate_map(routed: RoutedRetrievalResult) -> dict[str, RoutedCandidate]:
    return {c.chunk_id: c for c in routed.candidates}


def _merge_pool_for_query(routed: RoutedRetrievalResult, pool_size: int) -> list[RoutedCandidate]:
    return routed.candidates[:pool_size]


def _merge_multi_query_results(
    per_query: list[tuple[str, RoutedRetrievalResult]],
    *,
    pool_size: int = MERGE_POOL_PER_QUERY,
) -> dict[str, MergedCandidate]:
    """Merge per-query candidate pools; dedupe by chunk_id and track matched_queries."""
    merged: dict[str, MergedCandidate] = {}
    for search_query, routed in per_query:
        cand_map = _candidate_map(routed)
        for rc in _merge_pool_for_query(routed, pool_size):
            cid = rc.chunk_id
            existing = merged.get(cid)
            if existing is None:
                merged[cid] = _to_merged_candidate(rc, search_query=search_query)
                continue

            if search_query not in existing.matched_queries:
                existing.matched_queries.append(search_query)
            if rc.score > existing.score or (
                rc.score == existing.score and rc.tier_rank < existing.tier_rank
            ):
                existing.tier = rc.tier
                existing.tier_rank = rc.tier_rank
                existing.score = rc.score
                existing.result = rc.result
                existing.content_type = rc.content_type
                existing.source_title = rc.source_title
                existing.page = rc.page
                existing.text = rc.text
    return merged


async def _scoped_resource_retrieval(
    course_id: UUID,
    topic_external_id: str,
    search_queries: list[str],
    *,
    pool_size: int = SCOPED_CANDIDATE_POOL,
) -> list[MergedCandidate]:
    """Semantic search restricted to one resolved resource (by topic_external_id)."""
    best: dict[str, MergedCandidate] = {}
    for search_query in search_queries:
        hits = await query_chunks(
            course_id,
            search_query,
            None,
            n_results=pool_size,
            topic_external_id=topic_external_id,
        )
        for hit in hits:
            rc = _to_candidate(hit, "scoped", 0)
            cid = rc.chunk_id
            existing = best.get(cid)
            if existing is None:
                best[cid] = _to_merged_candidate(rc, search_query=search_query)
                continue
            if search_query not in existing.matched_queries:
                existing.matched_queries.append(search_query)
            if hit.score > existing.score:
                existing.score = hit.score
                existing.result = hit
                existing.text = hit.text

    ranked = sorted(best.values(), key=lambda m: (-m.score, m.page or 0))
    return ranked


def _select_final_with_coverage(
    merged: dict[str, MergedCandidate],
    per_query: list[tuple[str, RoutedRetrievalResult]],
    final_top_k: int,
    query_identifiers: list,
    *,
    intent: QueryIntent | None = None,
    scoped_priority: list[MergedCandidate] | None = None,
    resource_priority_slots: int = 0,
    pool_size: int = MERGE_POOL_PER_QUERY,
) -> list[MergedCandidate]:
    """Coverage-aware selection with optional scoped-resource priority slots."""
    selected: list[MergedCandidate] = []
    selected_ids: set[str] = set()

    if scoped_priority and resource_priority_slots > 0:
        for candidate in scoped_priority:
            if len(selected) >= resource_priority_slots:
                break
            if candidate.chunk_id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate.chunk_id)

    for _search_query, routed in per_query:
        for rc in _merge_pool_for_query(routed, pool_size):
            cid = rc.chunk_id
            if cid in selected_ids or cid not in merged:
                continue
            selected.append(merged[cid])
            selected_ids.add(cid)
            break
        if len(selected) >= final_top_k:
            return selected[:final_top_k]

    remaining = [m for cid, m in merged.items() if cid not in selected_ids]
    remaining.sort(key=lambda m: _candidate_rank_key(m, query_identifiers, intent))
    for candidate in remaining:
        if len(selected) >= final_top_k:
            break
        selected.append(candidate)
        selected_ids.add(candidate.chunk_id)

    return selected[:final_top_k]


def _to_final_search_results(selected: list[MergedCandidate]) -> list[SearchResult]:
    results: list[SearchResult] = []
    for i, candidate in enumerate(selected, start=1):
        results.append(
            candidate.result.model_copy(
                update={
                    "rank": i,
                    "matched_queries": list(candidate.matched_queries),
                    "routing_tier": candidate.tier,
                },
            ),
        )
    return results


def _resolve_search_queries(plan: QueryIntentResult, original_question: str) -> list[str]:
    queries = [q.strip() for q in plan.search_queries if q.strip()]
    if queries:
        return queries
    question = original_question.strip()
    return [question] if question else []


async def planned_retrieval(
    course_id: UUID,
    original_question: str,
    plan: QueryIntentResult,
    *,
    final_top_k: int = FINAL_TOP_K,
    per_query_top_k: int = PER_QUERY_TOP_K,
) -> PlannedRetrievalResult:
    """Run routed retrieval for each planner search query, merge, and select final chunks."""
    search_queries = _resolve_search_queries(plan, original_question)
    if not search_queries:
        return PlannedRetrievalResult(
            routing=RoutingInfo(
                intent=plan.intent.value,
                primary_content_types=[],
                secondary_content_types=[],
                fallback_content_types=[],
            ),
            search_queries=[],
            per_query=[],
            merged_candidates=[],
            final_results=[],
        )

    resource_matches, evidence_scope = await resolve_course_resources(
        course_id, original_question, plan,
    )
    authoritative = unique_high_confidence_match(resource_matches)

    routed_results = await asyncio.gather(
        *[
            routed_search(course_id, query, plan.intent, top_k=per_query_top_k)
            for query in search_queries
        ],
    )
    per_query = list(zip(search_queries, routed_results, strict=True))
    query_identifiers = collect_query_identifiers(original_question, *search_queries)
    merged_map = _merge_multi_query_results(per_query)
    merged_list = sorted(
        merged_map.values(),
        key=lambda m: _candidate_rank_key(m, query_identifiers, plan.intent),
    )

    scoped_priority: list[MergedCandidate] = []
    priority_slots = 0
    user_named_work = any(
        ident.number is not None and ident.kind in {"hw", "assignment", "lab", "project", "quiz"}
        for ident in extract_identifiers(original_question)
    )
    if authoritative and evidence_scope == EvidenceScope.RESOURCE_CONTENT:
        topic_id = authoritative.resource.topic_external_id
        dropbox_topic = topic_id.startswith("assignment:")
        if not dropbox_topic or user_named_work:
            scoped_priority = await _scoped_resource_retrieval(
                course_id,
                topic_id,
                search_queries,
            )
            priority_slots = _resource_priority_slots(final_top_k)

    selected = _select_final_with_coverage(
        merged_map,
        per_query,
        final_top_k,
        query_identifiers,
        intent=plan.intent,
        scoped_priority=scoped_priority or None,
        resource_priority_slots=priority_slots,
    )
    final_results = _to_final_search_results(selected)

    return PlannedRetrievalResult(
        routing=per_query[0][1].routing,
        search_queries=search_queries,
        per_query=per_query,
        merged_candidates=merged_list,
        final_results=final_results,
        resource_matches=resource_matches,
        evidence_scope=evidence_scope.value,
    )
