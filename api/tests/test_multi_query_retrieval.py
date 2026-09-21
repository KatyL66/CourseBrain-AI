import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from app.models.schemas import SearchResult, SourceMetadata
from app.services.query_intent import (
    QuestionType,
    QueryIntent,
    QueryIntentResult,
)
from app.services.resource_resolver import EvidenceScope
from app.services.retrieval_router import (
    PlannedRetrievalResult,
    RoutedCandidate,
    RoutedRetrievalResult,
    RoutingInfo,
    _merge_multi_query_results,
    _resolve_search_queries,
    _select_final_with_coverage,
    planned_retrieval,
)


def _hit(score: float, *, title: str = "doc", page: int | None = None) -> SearchResult:
    return SearchResult(
        chunk_id=uuid4(),
        rank=0,
        text=f"content {score} {title}",
        score=score,
        distance=1 - score,
        source=SourceMetadata(
            course_id="c1",
            content_type="lecture",
            topic_id="t1",
            topic_title=title,
            url="https://example.com",
            page=page,
        ),
    )


def _cand(hit: SearchResult, tier: str, tier_rank: int) -> RoutedCandidate:
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


def _routed(hits: list[SearchResult], *, intent: str = "LEARNING") -> RoutedRetrievalResult:
    candidates = [_cand(h, "primary", 0) for h in hits]
    final = [h.model_copy(update={"rank": i}) for i, h in enumerate(hits, start=1)]
    return RoutedRetrievalResult(
        routing=RoutingInfo(
            intent=intent,
            primary_content_types=["lecture"],
            secondary_content_types=[],
            fallback_content_types=["other"],
            tiers_searched=["primary"],
            enough_from_primary=True,
        ),
        candidates=candidates,
        final_results=final,
    )


class ResolveSearchQueriesTests(unittest.TestCase):
    def test_empty_search_queries_falls_back_to_original(self):
        plan = QueryIntentResult(
            intent=QueryIntent.COURSE_INFO,
            confidence=0.9,
            search_queries=[],
        )
        self.assertEqual(
            _resolve_search_queries(plan, "When is the final exam?"),
            ["When is the final exam?"],
        )

    def test_uses_planner_queries_when_present(self):
        plan = QueryIntentResult(
            intent=QueryIntent.LEARNING,
            confidence=0.9,
            search_queries=["system definition", "examples of systems"],
        )
        self.assertEqual(
            _resolve_search_queries(plan, "What is a system?"),
            ["system definition", "examples of systems"],
        )


class MergeMultiQueryTests(unittest.TestCase):
    def test_duplicate_chunk_merged_with_multiple_matched_queries(self):
        shared = _hit(0.8, title="definition slide")
        q1 = _routed([shared])
        other = _hit(0.7, title="examples slide")
        q2 = _routed([shared, other])

        merged = _merge_multi_query_results([
            ("system definition", q1),
            ("examples of systems", q2),
        ])

        self.assertEqual(len(merged), 2)
        shared_merged = merged[str(shared.chunk_id)]
        self.assertEqual(
            shared_merged.matched_queries,
            ["system definition", "examples of systems"],
        )

    def test_merge_includes_candidates_beyond_per_query_final_top5(self):
        top = _hit(0.9, title="syllabus")
        buried = _hit(0.35, title="Lab 2 - Gauss")
        routed = RoutedRetrievalResult(
            routing=RoutingInfo(
                intent="ASSIGNMENT",
                primary_content_types=["assignment"],
                secondary_content_types=["syllabus"],
                fallback_content_types=["other"],
            ),
            candidates=[_cand(top, "secondary", 1), _cand(buried, "primary", 0)],
            final_results=[top.model_copy(update={"rank": 1})],
        )
        merged = _merge_multi_query_results([("lab2 requirements", routed)])
        self.assertIn(str(buried.chunk_id), merged)
        self.assertEqual(merged[str(buried.chunk_id)].source_title, "Lab 2 - Gauss")


class CoverageSelectionTests(unittest.TestCase):
    def test_one_pick_per_query_before_filling(self):
        h1 = _hit(0.9, title="definition")
        h2 = _hit(0.85, title="characteristics")
        h3 = _hit(0.8, title="examples")
        per_query = [
            ("system definition", _routed([h1])),
            ("key characteristics of a system", _routed([h2])),
            ("examples of systems", _routed([h3])),
        ]
        merged = _merge_multi_query_results(per_query)
        selected = _select_final_with_coverage(merged, per_query, final_top_k=8, query_identifiers=[])

        self.assertEqual(len(selected), 3)
        titles = {s.source_title for s in selected}
        self.assertEqual(titles, {"definition", "characteristics", "examples"})

    def test_fill_remaining_by_score_when_slots_left(self):
        h1 = _hit(0.9, title="definition")
        h2 = _hit(0.88, title="definition-extra")
        per_query = [
            ("system definition", _routed([h1, h2])),
        ]
        merged = _merge_multi_query_results(per_query)
        selected = _select_final_with_coverage(merged, per_query, final_top_k=2, query_identifiers=[])
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0].source_title, "definition")


class PlannedRetrievalIntegrationTests(unittest.IsolatedAsyncioTestCase):
    course_id = UUID("00000000-0000-0000-0000-000000000001")

    def _patch_resolver(self):
        return patch(
            "app.services.retrieval_router.resolve_course_resources",
            AsyncMock(return_value=([], EvidenceScope.GLOBAL)),
        )

    async def test_single_query_planner_runs_one_routed_search(self):
        plan = QueryIntentResult(
            intent=QueryIntent.COURSE_INFO,
            confidence=0.95,
            topic="final exam",
            question_type=QuestionType.FACTUAL_LOOKUP,
            search_queries=["final exam date and time"],
        )
        hit = _hit(0.9, title="syllabus")

        with patch(
            "app.services.retrieval_router.routed_search",
            AsyncMock(return_value=_routed([hit], intent="COURSE_INFO")),
        ) as mock_search, self._patch_resolver():
            result = await planned_retrieval(
                self.course_id,
                "When is the final exam?",
                plan,
                final_top_k=5,
            )

        mock_search.assert_awaited_once_with(
            self.course_id,
            "final exam date and time",
            QueryIntent.COURSE_INFO,
            top_k=5,
        )
        self.assertEqual(len(result.final_results), 1)
        self.assertEqual(result.final_results[0].source.topic_title, "syllabus")

    async def test_multi_query_executes_each_search_query(self):
        plan = QueryIntentResult(
            intent=QueryIntent.LEARNING,
            confidence=0.9,
            topic="system",
            question_type=QuestionType.CONCEPT_EXPLANATION,
            search_queries=[
                "system definition",
                "key characteristics of a system",
                "examples of systems",
            ],
        )

        async def fake_routed(course_id, query, intent, top_k=5):
            hit = _hit(0.8, title=query)
            return _routed([hit])

        with patch(
            "app.services.retrieval_router.routed_search",
            side_effect=fake_routed,
        ) as mock_search, self._patch_resolver():
            result = await planned_retrieval(
                self.course_id,
                "What is a system?",
                plan,
            )

        self.assertEqual(mock_search.await_count, 3)
        self.assertEqual(len(result.final_results), 3)
        self.assertEqual(len(result.search_queries), 3)

    async def test_zero_results_from_one_query_still_returns_others(self):
        plan = QueryIntentResult(
            intent=QueryIntent.LEARNING,
            confidence=0.9,
            search_queries=["missing topic", "system definition"],
        )
        hit = _hit(0.8, title="definition")

        async def fake_routed(course_id, query, intent, top_k=5):
            if query == "missing topic":
                return _routed([])
            return _routed([hit])

        with patch("app.services.retrieval_router.routed_search", side_effect=fake_routed), self._patch_resolver():
            result = await planned_retrieval(self.course_id, "What is a system?", plan)

        self.assertEqual(len(result.final_results), 1)

    async def test_empty_planner_queries_fallback_to_original_question(self):
        plan = QueryIntentResult(
            intent=QueryIntent.LEARNING,
            confidence=0.0,
            search_queries=[],
        )
        hit = _hit(0.75, title="lecture")

        with patch(
            "app.services.retrieval_router.routed_search",
            AsyncMock(return_value=_routed([hit])),
        ) as mock_search, self._patch_resolver():
            result = await planned_retrieval(
                self.course_id,
                "What is a system?",
                plan,
            )

        mock_search.assert_awaited_once_with(
            self.course_id,
            "What is a system?",
            QueryIntent.LEARNING,
            top_k=5,
        )
        self.assertEqual(len(result.final_results), 1)

    async def test_intent_passed_to_each_routed_search(self):
        plan = QueryIntentResult(
            intent=QueryIntent.ASSIGNMENT,
            confidence=0.9,
            search_queries=["HW3 submission requirements", "HW3 rubric"],
        )

        with patch(
            "app.services.retrieval_router.routed_search",
            AsyncMock(return_value=_routed([])),
        ) as mock_search, self._patch_resolver():
            await planned_retrieval(self.course_id, "HW3?", plan)

        for call in mock_search.await_args_list:
            self.assertEqual(call.args[2], QueryIntent.ASSIGNMENT)

    async def test_course_id_passed_to_each_routed_search(self):
        plan = QueryIntentResult(
            intent=QueryIntent.LEARNING,
            confidence=0.9,
            search_queries=["a", "b"],
        )

        with patch(
            "app.services.retrieval_router.routed_search",
            AsyncMock(return_value=_routed([])),
        ) as mock_search, self._patch_resolver():
            await planned_retrieval(self.course_id, "question", plan)

        for call in mock_search.await_args_list:
            self.assertEqual(call.args[0], self.course_id)


if __name__ == "__main__":
    unittest.main()
