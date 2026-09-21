import unittest

from app.models.schemas import SearchResult, SourceMetadata
from app.services.query_intent import QueryIntent
from unittest.mock import patch
from uuid import uuid4

from app.services.retrieval_router import (
    INTENT_SOURCE_PRIORITY,
    RoutedCandidate,
    ROUTING_POLICY,
    _dedupe_keep_best,
    _enough_hits,
    _policy_from_priority,
    _rank_candidates,
    _rank_score,
    routed_search,
)


def _hit(score: float, content_type: str = "lecture", title: str = "doc") -> SearchResult:
    return SearchResult(
        chunk_id=uuid4(),
        rank=0,
        text=f"content {score}",
        score=score,
        distance=1 - score,
        source=SourceMetadata(
            course_id="c1",
            content_type=content_type,
            topic_id="t1",
            topic_title=title,
            url="https://example.com",
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
        page=None,
        text=hit.text,
        result=hit,
    )


class RetrievalRouterLogicTests(unittest.TestCase):
    def test_enough_hits_by_count(self):
        hits = [_hit(0.35), _hit(0.32), _hit(0.31)]
        self.assertTrue(_enough_hits(hits))

    def test_enough_hits_by_top_score(self):
        hits = [_hit(0.45)]
        self.assertTrue(_enough_hits(hits))

    def test_not_enough_hits(self):
        hits = [_hit(0.20), _hit(0.15)]
        self.assertFalse(_enough_hits(hits))

    def test_dedupe_keeps_best_score(self):
        h = _hit(0.5)
        primary = _cand(h, "primary", 0)
        fallback = _cand(h, "fallback", 2)
        fallback.result = fallback.result.model_copy(update={"score": 0.55})
        fallback.score = 0.55
        result = _dedupe_keep_best([primary, fallback])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].tier, "fallback")
        self.assertEqual(result[0].score, 0.55)

    def test_rank_orders_by_score_not_tier(self):
        primary_low = _cand(_hit(0.30, "assignment"), "primary", 0)
        secondary_high = _cand(_hit(0.42, "lecture"), "secondary", 1)
        ranked = _rank_candidates([primary_low, secondary_high], [])
        self.assertEqual(ranked[0].tier, "secondary")
        self.assertEqual(ranked[0].score, 0.42)

    def test_identifier_boost_can_promote_matching_chunk(self):
        from app.services.identifier_match import extract_identifiers

        generic = _cand(_hit(0.44, "assignment"), "primary", 0)
        generic.text = "Your project is to prepare diagrams"
        hw_chunk = _cand(_hit(0.42, "lecture"), "secondary", 1)
        hw_chunk.text = "HW 1: 1-page summary of chapter 1"
        query_ids = extract_identifiers("hw1 是啥")
        ranked = _rank_candidates([generic, hw_chunk], query_ids)
        self.assertEqual(ranked[0].text, hw_chunk.text)

    def test_tier_prior_breaks_near_tie_in_favor_of_primary(self):
        primary = _cand(_hit(0.424, "assignment"), "primary", 0)
        secondary = _cand(_hit(0.423, "lecture"), "secondary", 1)
        self.assertGreater(_rank_score(primary.score, primary.tier_rank),
                           _rank_score(secondary.score, secondary.tier_rank))
        ranked = _rank_candidates([secondary, primary], [])
        self.assertEqual(ranked[0].tier, "primary")

    def test_assignment_policy_includes_lecture(self):
        policy = ROUTING_POLICY[QueryIntent.ASSIGNMENT]
        all_types = policy["primary"] + policy["secondary"] + policy["fallback"]
        self.assertIn("lecture", all_types)
        self.assertIn("assignment", policy["primary"])

    def test_learning_policy_includes_assignment(self):
        policy = ROUTING_POLICY[QueryIntent.LEARNING]
        all_types = policy["primary"] + policy["secondary"] + policy["fallback"]
        self.assertIn("assignment", all_types)
        self.assertIn("lecture", policy["primary"])

    def test_dropbox_objects_are_excluded_from_all_corpus_intents(self):
        from app.services.retrieval_router import _exclude_dropbox_objects

        syllabus = _cand(_hit(0.40, "syllabus", "Course Schedule"), "primary", 0)
        dropbox = _cand(_hit(0.99, "assignment", "HW3 initial"), "fallback", 2)
        dropbox.result.source.source_type = "assignment"
        lecture = _cand(_hit(0.50, "lecture", "Week 1"), "secondary", 1)
        kept = _exclude_dropbox_objects([dropbox, syllabus, lecture])
        titles = {c.source_title for c in kept}
        self.assertEqual(titles, {"Course Schedule", "Week 1"})

    def test_course_info_policy_includes_lecture(self):
        policy = ROUTING_POLICY[QueryIntent.COURSE_INFO]
        all_types = policy["primary"] + policy["secondary"] + policy["fallback"]
        self.assertIn("lecture", all_types)

    def test_course_info_assignment_is_last_fallback(self):
        policy = ROUTING_POLICY[QueryIntent.COURSE_INFO]
        self.assertIn("syllabus", policy["primary"])
        self.assertIn("assignment", policy["fallback"])
        self.assertNotIn("assignment", policy["primary"])
        self.assertNotIn("assignment", policy["secondary"])

    def test_course_info_syllabus_prior_beats_near_assignment(self):
        overview = _cand(_hit(0.50, "syllabus", "Overview"), "primary", 0)
        project = _cand(_hit(0.55, "assignment", "Project Description"), "fallback", 2)
        ranked = _rank_candidates(
            [project, overview], [], QueryIntent.COURSE_INFO,
        )
        self.assertEqual(ranked[0].source_title, "Overview")

    def test_all_content_types_covered_per_intent(self):
        all_types = {"syllabus", "lecture", "assignment", "announcement", "other"}
        for intent, priority in INTENT_SOURCE_PRIORITY.items():
            if intent == QueryIntent.MIXED:
                continue
            policy = _policy_from_priority(priority)
            covered = set(policy["primary"] + policy["secondary"] + policy["fallback"])
            self.assertEqual(covered, all_types, msg=intent.value)


class CourseInfoRoutedSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_enough_overview_skips_project_description(self):
        overview = _hit(0.55, "syllabus", "Overview")
        overview.text = "Homework 120 points of the total grade"

        async def fake_query(_course_id, _query, content_types=None, n_results=10, **_kwargs):
            types = content_types or []
            if "syllabus" in types:
                return [overview]
            return [_hit(0.90, "assignment", "Project Description")]

        with patch("app.services.retrieval_router.query_chunks", side_effect=fake_query):
            result = await routed_search(
                uuid4(), "作业占比总成绩百分之多少", QueryIntent.COURSE_INFO,
            )

        titles = [hit.source.topic_title for hit in result.final_results]
        self.assertIn("Overview", titles)
        self.assertNotIn("Project Description", titles)
        self.assertEqual(result.routing.tiers_searched, ["primary"])
        self.assertTrue(result.routing.enough_from_primary)

    async def test_missing_syllabus_still_reaches_assignment_docs(self):
        project = _hit(0.70, "assignment", "Project Description")

        async def fake_query(_course_id, _query, content_types=None, n_results=10, **_kwargs):
            types = content_types or []
            if "assignment" in types:
                return [project]
            return []

        with patch("app.services.retrieval_router.query_chunks", side_effect=fake_query):
            result = await routed_search(uuid4(), "When is the final exam?", QueryIntent.COURSE_INFO)

        titles = [hit.source.topic_title for hit in result.final_results]
        self.assertIn("Project Description", titles)
        self.assertIn("fallback", result.routing.tiers_searched)

    async def test_course_grade_question_does_not_fallback_to_assignment(self):
        project = _hit(0.90, "assignment", "Project Description")

        async def fake_query(_course_id, _query, content_types=None, n_results=10, **_kwargs):
            types = content_types or []
            if "assignment" in types:
                return [project]
            return []

        with patch("app.services.retrieval_router.query_chunks", side_effect=fake_query):
            result = await routed_search(
                uuid4(), "这个课作业占整个 grade 的多少？", QueryIntent.COURSE_INFO,
            )

        titles = [hit.source.topic_title for hit in result.final_results]
        self.assertNotIn("Project Description", titles)


if __name__ == "__main__":
    unittest.main()
