"""Tests for course resource resolution and evidence scope decisions."""

import unittest

from app.services.identifier_match import CourseIdentifier, extract_identifiers
from app.services.query_intent import QueryIntent, QueryIntentResult, QuestionType
from app.services.resource_resolver import (
    CourseResource,
    EvidenceScope,
    decide_evidence_scope,
    load_course_resources,
    resolve_resources,
    resource_identity,
    unique_high_confidence_match,
)


def _phys152_catalog() -> list[CourseResource]:
    return [
        CourseResource(
            topic_external_id="10193209",
            topic_title="Lab 2 - Gauss_s Law, Symmetry Models, and Graphical Analysis",
            module_name="Lab Assignments > Lab 2",
            content_type="assignment",
        ),
        CourseResource(
            topic_external_id="schedule1",
            topic_title="152 Lab Schedule",
            module_name="Lab Information",
            content_type="other",
        ),
        CourseResource(
            topic_external_id="syllabus1",
            topic_title="Lab Syllabus",
            module_name="Lab Information",
            content_type="syllabus",
        ),
        CourseResource(
            topic_external_id="lab1",
            topic_title="Lab 1 - Mapping of Electric Potential and Electric Fields Lines",
            module_name="Lab Assignments > Lab 1",
            content_type="assignment",
        ),
        CourseResource(
            topic_external_id="hw1",
            topic_title="Homework 1 - Chapter 1",
            module_name="Homework > HW 1",
            content_type="assignment",
        ),
        CourseResource(
            topic_external_id="lec3",
            topic_title="Lecture 3 - Electric Fields",
            module_name="Lectures > Week 3",
            content_type="lecture",
        ),
    ]


class IdentifierNormalizationTests(unittest.TestCase):
    def test_lab2_variants(self):
        for text in ("lab2", "lab 2", "lab #2", "Lab #2", "lab2是要干啥"):
            ids = extract_identifiers(text)
            self.assertTrue(any(i.key == "lab:2" for i in ids), msg=text)

    def test_hw1_and_assignment(self):
        self.assertEqual(extract_identifiers("hw1要交什么")[0].key, "hw:1")
        self.assertEqual(extract_identifiers("assignment 2讲什么")[0].key, "assignment:2")

    def test_lecture_identifier(self):
        self.assertEqual(extract_identifiers("lecture 3讲了啥")[0].key, "lecture:3")


class ResourceIdentityTests(unittest.TestCase):
    def test_lab2_from_title(self):
        resource = _phys152_catalog()[0]
        ident = resource_identity(resource)
        self.assertEqual(ident, CourseIdentifier(kind="lab", number=2))

    def test_schedule_has_no_lab_identity(self):
        resource = _phys152_catalog()[1]
        self.assertIsNone(resource_identity(resource))


class ResolveResourcesTests(unittest.TestCase):
    def test_lab2_resolves_to_gauss_pdf(self):
        matches = resolve_resources("lab2是要干啥", _phys152_catalog(), planner_topic="lab2")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].resource.topic_external_id, "10193209")
        self.assertGreaterEqual(matches[0].confidence, 0.85)

    def test_lab2_not_resolved_to_schedule(self):
        matches = resolve_resources("lab2是要干啥", _phys152_catalog())
        topic_ids = {m.resource.topic_external_id for m in matches}
        self.assertNotIn("schedule1", topic_ids)

    def test_no_identifier_returns_empty(self):
        self.assertEqual(resolve_resources("what is Gauss's law", _phys152_catalog()), [])

    def test_hw1_resolves(self):
        matches = resolve_resources("hw1要交什么", _phys152_catalog())
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].resource.topic_external_id, "hw1")

    def test_lecture3_resolves(self):
        matches = resolve_resources("lecture 3讲了啥", _phys152_catalog())
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].resource.topic_external_id, "lec3")


class EvidenceScopeTests(unittest.TestCase):
    def _plan(self, **kwargs) -> QueryIntentResult:
        defaults = dict(
            intent=QueryIntent.ASSIGNMENT,
            confidence=0.9,
            topic="lab2",
            question_type=QuestionType.ASSIGNMENT_HELP,
            search_queries=["lab2 requirements"],
        )
        defaults.update(kwargs)
        return QueryIntentResult(**defaults)

    def test_content_question_scopes_to_resource(self):
        matches = resolve_resources("lab2是要干啥", _phys152_catalog(), planner_topic="lab2")
        scope = decide_evidence_scope("lab2是要干啥", self._plan(), matches)
        self.assertEqual(scope, EvidenceScope.RESOURCE_CONTENT)

    def test_procedure_scopes_to_resource(self):
        matches = resolve_resources("Lab #2 procedure", _phys152_catalog())
        scope = decide_evidence_scope("Lab #2 procedure", self._plan(question_type=QuestionType.PROCEDURE), matches)
        self.assertEqual(scope, EvidenceScope.RESOURCE_CONTENT)

    def test_when_is_lab2_uses_logistics_scope(self):
        matches = resolve_resources("when is lab 2", _phys152_catalog(), planner_topic="lab 2")
        plan = self._plan(
            intent=QueryIntent.COURSE_INFO,
            question_type=QuestionType.FACTUAL_LOOKUP,
            topic="lab 2",
        )
        scope = decide_evidence_scope("when is lab 2", plan, matches)
        self.assertEqual(scope, EvidenceScope.RESOURCE_LOGISTICS)

    def test_gauss_law_without_lab_identifier_is_global(self):
        plan = QueryIntentResult(
            intent=QueryIntent.LEARNING,
            confidence=0.9,
            topic="Gauss's law",
            question_type=QuestionType.CONCEPT_EXPLANATION,
            search_queries=["Gauss's law definition"],
        )
        scope = decide_evidence_scope("what is Gauss's law", plan, [])
        self.assertEqual(scope, EvidenceScope.GLOBAL)

    def test_ambiguous_multiple_matches_is_global(self):
        catalog = _phys152_catalog() + [
            CourseResource(
                topic_external_id="lab2b",
                topic_title="Lab 2 - Alternate Worksheet",
                module_name="Lab Assignments > Lab 2",
                content_type="assignment",
            ),
        ]
        matches = resolve_resources("lab 2", catalog)
        self.assertGreater(len(matches), 1)
        scope = decide_evidence_scope("lab 2", self._plan(), matches)
        self.assertEqual(scope, EvidenceScope.GLOBAL)
        self.assertIsNone(unique_high_confidence_match(matches))

    def test_no_match_fallback_global(self):
        scope = decide_evidence_scope("lab2是要干啥", self._plan(), [])
        self.assertEqual(scope, EvidenceScope.GLOBAL)


class UniqueMatchTests(unittest.TestCase):
    def test_single_high_confidence(self):
        matches = resolve_resources("lab2", _phys152_catalog())
        self.assertIsNotNone(unique_high_confidence_match(matches))

    def test_multiple_matches_returns_none(self):
        catalog = _phys152_catalog() + [
            CourseResource(
                topic_external_id="lab2dup",
                topic_title="Lab 2 - Extra",
                module_name="Lab Assignments > Lab 2",
                content_type="assignment",
            ),
        ]
        matches = resolve_resources("lab 2", catalog)
        self.assertIsNone(unique_high_confidence_match(matches))


class LoadCourseResourcesIntegrationTests(unittest.TestCase):
    def test_load_phys152_has_lab2(self):
        from uuid import UUID

        course_id = UUID("e97180f5-cd3d-42ce-b931-e054fdb7c705")
        resources = load_course_resources(course_id)
        if not resources:
            self.skipTest("Chroma collection empty in this environment")
        titles = [r.topic_title for r in resources]
        self.assertTrue(any("Lab 2" in t and "Gauss" in t for t in titles))


if __name__ == "__main__":
    unittest.main()
