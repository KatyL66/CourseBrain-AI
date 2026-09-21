import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.db.object_store import AssignmentObject, save_assignments
from app.services.assignment_query import (
    AssignmentAspect,
    assignment_identifier_key,
    assignment_source_reference,
    classify_assignment_aspect,
    resolve_named_assignment,
    structured_assignment_answer,
)
from app.services.identifier_match import collect_query_identifiers


class AssignmentAspectTests(unittest.TestCase):
    def test_what_is_hw3_is_instructions(self):
        self.assertEqual(classify_assignment_aspect("What is HW3?"), AssignmentAspect.INSTRUCTIONS)
        self.assertEqual(classify_assignment_aspect("HW3是啥"), AssignmentAspect.INSTRUCTIONS)
        self.assertEqual(classify_assignment_aspect("HW3要求是什么"), AssignmentAspect.INSTRUCTIONS)
        self.assertEqual(
            classify_assignment_aspect("What do I need to submit for HW3?"),
            AssignmentAspect.INSTRUCTIONS,
        )

    def test_when_due(self):
        self.assertEqual(classify_assignment_aspect("When is HW3 due?"), AssignmentAspect.DUE)
        self.assertEqual(classify_assignment_aspect("HW3什么时候due？"), AssignmentAspect.DUE)
        self.assertEqual(classify_assignment_aspect("hw3今晚截止吗"), AssignmentAspect.DUE)
        self.assertEqual(classify_assignment_aspect("hw3啥时候due"), AssignmentAspect.DUE)

    def test_where_submit(self):
        self.assertEqual(classify_assignment_aspect("Where do I submit HW3?"), AssignmentAspect.SUBMIT)
        self.assertEqual(classify_assignment_aspect("HW3在哪里提交"), AssignmentAspect.SUBMIT)

    def test_open(self):
        self.assertEqual(classify_assignment_aspect("Open HW3"), AssignmentAspect.OPEN)
        self.assertEqual(classify_assignment_aspect("打开HW3"), AssignmentAspect.OPEN)


class AssignmentIdentifierTests(unittest.TestCase):
    def test_hw_title(self):
        self.assertEqual(assignment_identifier_key("HW 3"), "hw:3")
        self.assertEqual(assignment_identifier_key("HW3 initial"), "hw:3")
        self.assertEqual(assignment_identifier_key("Homework 2: EPM chapter 2"), "hw:2")
        self.assertEqual(assignment_identifier_key("Assignment 3"), "hw:3")
        self.assertEqual(assignment_identifier_key("作业3"), "hw:3")


class NamedAssignmentJourneyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = settings.data_dir
        settings.data_dir = str(self.tmp)
        self.course_id = uuid4()
        self.hw3 = AssignmentObject(
            object_id="9001",
            name="HW 3",
            canonical_url="https://lms.example.edu/d2l/lms/dropbox/user/folder_submit_files.d2l?db=9001&ou=1001",
            identifier="hw:3",
            due_at="2026-09-16T06:59:00.000Z",
            submission_type="File",
        )
        save_assignments(self.course_id, [self.hw3])

    def tearDown(self):
        settings.data_dir = self._orig

    def _resolve(self, question: str):
        ids = collect_query_identifiers(question)
        return resolve_named_assignment(self.course_id, ids)

    def test_what_is_hw3_resolves_object(self):
        obj = self._resolve("What is HW3?")
        self.assertIsNotNone(obj)
        self.assertEqual(obj.object_id, "9001")
        self.assertEqual(classify_assignment_aspect("What is HW3?"), AssignmentAspect.INSTRUCTIONS)

    def test_submit_content_is_instructions_not_location(self):
        self.assertEqual(
            classify_assignment_aspect("What do I need to submit for HW3?"),
            AssignmentAspect.INSTRUCTIONS,
        )
        self.assertEqual(self._resolve("What do I need to submit for HW3?").object_id, "9001")

    def test_due_uses_structured_due_at_not_availability(self):
        question = "When is HW3 due?"
        obj = self._resolve(question)
        answer = structured_assignment_answer(obj, AssignmentAspect.DUE, question)
        self.assertIn("Sep 15, 2026", answer)
        self.assertNotIn("Available until", answer)
        self.assertNotIn("Ends ", answer)
        self.assertIn("[SOURCE 1]", answer)
        self.assertEqual(
            assignment_source_reference(obj).url,
            self.hw3.canonical_url,
        )

    def test_missing_due_is_explicit(self):
        bare = AssignmentObject(
            object_id="9002",
            name="HW 4",
            canonical_url="https://example.test/dropbox/9002",
            identifier="hw:4",
            due_at=None,
        )
        save_assignments(self.course_id, [bare])
        obj = self._resolve("When is HW4 due?")
        answer = structured_assignment_answer(obj, AssignmentAspect.DUE, "When is HW4 due?")
        self.assertIn("does not list a due date", answer)
        self.assertNotIn("Available until", answer)

    def test_where_submit_uses_dropbox_url(self):
        question = "Where do I submit HW3?"
        obj = self._resolve(question)
        answer = structured_assignment_answer(obj, AssignmentAspect.SUBMIT, question)
        ref = assignment_source_reference(obj)
        self.assertIn("dropbox", answer.lower() + ref.url.lower())
        self.assertEqual(ref.url, self.hw3.canonical_url)
        self.assertEqual(ref.module, "Assignments")

    def test_open_hw3_uses_dropbox_url(self):
        question = "Open HW3"
        obj = self._resolve(question)
        answer = structured_assignment_answer(obj, AssignmentAspect.OPEN, question)
        ref = assignment_source_reference(obj)
        self.assertIn("Open HW 3", answer)
        self.assertEqual(ref.url, self.hw3.canonical_url)

    def test_hw3_initial_is_unique_among_initial_final_folders(self):
        folders = [
            AssignmentObject(
                object_id="1",
                name="HW1 initial",
                canonical_url="https://example.test/1",
                identifier="hw:1",
                due_at="2026-09-05T03:00:00.000Z",
            ),
            AssignmentObject(
                object_id="2",
                name="HW2 initial",
                canonical_url="https://example.test/2",
                identifier="hw:2",
                due_at="2026-09-12T03:00:00.000Z",
            ),
            AssignmentObject(
                object_id="3",
                name="HW1 final",
                canonical_url="https://example.test/3",
                identifier="hw:1",
                due_at="2026-09-12T03:00:00.000Z",
            ),
            AssignmentObject(
                object_id="4",
                name="HW3 initial",
                canonical_url="https://example.test/4",
                identifier="hw:3",
                due_at="2026-09-19T03:00:00.000Z",
            ),
        ]
        save_assignments(self.course_id, folders)
        obj = self._resolve("hw3啥时候due")
        self.assertIsNotNone(obj)
        self.assertEqual(obj.object_id, "4")
        self.assertEqual(obj.name, "HW3 initial")
        answer = structured_assignment_answer(obj, AssignmentAspect.DUE, "hw3啥时候due")
        self.assertIn("Sep 18, 2026", answer)

    def test_object_context_does_not_mention_availability(self):
        from app.services.rag import _assignment_object_context

        block = _assignment_object_context(self.hw3)
        self.assertIn("Due date (structured)", block)
        self.assertIn("Sep 15, 2026", block)
        self.assertNotIn("Available until", block)
        self.assertNotIn("Ends ", block)

    def test_concept_question_does_not_resolve(self):
        self.assertIsNone(self._resolve("What is a system?"))

    def test_availability_end_must_not_be_stored_as_due(self):
        """due_at is only the Dropbox DueDate field, never Availability.EndDate."""
        self.assertIsNotNone(self.hw3.due_at)
        self.assertNotIn("2023", self.hw3.due_at)


class AssignmentFirstFallbackTests(unittest.TestCase):
    """Named homework exists in Content before an Assignments folder exists."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = settings.data_dir
        settings.data_dir = str(self.tmp)
        self.course_id = uuid4()

    def tearDown(self):
        settings.data_dir = self._orig

    def test_hw3_missing_object_after_assignments_synced(self):
        from app.services.assignment_query import AssignmentLookupStatus, lookup_named_assignment

        save_assignments(
            self.course_id,
            [
                AssignmentObject(
                    object_id="1",
                    name="HW 1",
                    canonical_url="https://example.test/1",
                    identifier="hw:1",
                ),
                AssignmentObject(
                    object_id="2",
                    name="HW2",
                    canonical_url="https://example.test/2",
                    identifier="hw:2",
                ),
            ],
        )
        status, obj = lookup_named_assignment(
            self.course_id, collect_query_identifiers("hw3是啥")
        )
        self.assertEqual(status, AssignmentLookupStatus.MISSING_OBJECT)
        self.assertIsNone(obj)

    def test_unsynced_assignment_source(self):
        from app.services.assignment_query import AssignmentLookupStatus, lookup_named_assignment

        status, obj = lookup_named_assignment(
            self.course_id, collect_query_identifiers("hw3是啥")
        )
        self.assertEqual(status, AssignmentLookupStatus.SOURCE_UNSYNCED)
        self.assertIsNone(obj)

    def test_concept_question_is_not_named_assignment(self):
        from app.services.assignment_query import AssignmentLookupStatus, lookup_named_assignment

        status, obj = lookup_named_assignment(
            self.course_id, collect_query_identifiers("What is a system?")
        )
        self.assertEqual(status, AssignmentLookupStatus.NOT_NAMED)
        self.assertIsNone(obj)

    def test_grading_weight_question_is_not_named_hw(self):
        from app.services.assignment_query import AssignmentLookupStatus, lookup_named_assignment

        save_assignments(
            self.course_id,
            [
                AssignmentObject(
                    object_id="4",
                    name="HW3 initial",
                    canonical_url="https://example.test/4",
                    identifier="hw:3",
                ),
            ],
        )
        user_ids = collect_query_identifiers("作业占比总成绩百分之多少")
        status, obj = lookup_named_assignment(self.course_id, user_ids)
        self.assertEqual(status, AssignmentLookupStatus.NOT_NAMED)
        self.assertIsNone(obj)
        planner_ids = collect_query_identifiers(
            "作业占比总成绩百分之多少", "HW3 grading weight"
        )
        hijack_status, hijack = lookup_named_assignment(self.course_id, planner_ids)
        self.assertEqual(hijack_status, AssignmentLookupStatus.FOUND)
        self.assertEqual(hijack.object_id, "4")

    def test_content_fallback_note_is_source_aware(self):
        from app.services.assignment_query import (
            AssignmentLookupStatus,
            named_assignment_content_fallback_note,
        )

        due = named_assignment_content_fallback_note(
            AssignmentAspect.DUE, AssignmentLookupStatus.MISSING_OBJECT
        )
        self.assertIn("not a Brightspace Assignment DueDate", due)
        self.assertIn("Available until", due)
        submit = named_assignment_content_fallback_note(
            AssignmentAspect.SUBMIT, AssignmentLookupStatus.MISSING_OBJECT
        )
        self.assertIn("Do not invent", submit)
        self.assertIn("Dropbox", submit)
        what = named_assignment_content_fallback_note(
            AssignmentAspect.INSTRUCTIONS, AssignmentLookupStatus.MISSING_OBJECT
        )
        self.assertIn("explicitly mentions this identifier", what)


class HnswErrorClassificationTests(unittest.TestCase):
    def test_detects_missing_on_disk(self):
        from app.db.chroma_store import is_hnsw_missing_on_disk

        err = RuntimeError(
            "Error executing plan: Internal error: Error creating hnsw segment reader: Nothing found on disk"
        )
        self.assertTrue(is_hnsw_missing_on_disk(err))
        self.assertFalse(is_hnsw_missing_on_disk(RuntimeError("FileDataError: Failed to open stream")))


class AssignmentIngestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from app.db import chroma_store

        self.tmp = Path(tempfile.mkdtemp())
        self._orig_dir = settings.data_dir
        self._orig_paths = (
            chroma_store.DATA_DIR,
            chroma_store.COURSES_FILE,
            chroma_store.CHROMA_DIR,
            chroma_store._client,
        )
        settings.data_dir = str(self.tmp)
        chroma_store.DATA_DIR = self.tmp
        chroma_store.COURSES_FILE = self.tmp / "courses.json"
        chroma_store.CHROMA_DIR = self.tmp / "chroma"
        chroma_store._client = None

    async def asyncTearDown(self):
        from app.db import chroma_store

        settings.data_dir = self._orig_dir
        (
            chroma_store.DATA_DIR,
            chroma_store.COURSES_FILE,
            chroma_store.CHROMA_DIR,
            chroma_store._client,
        ) = self._orig_paths

    async def test_ingest_persists_structured_assignment_without_text(self):
        from app.db.chroma_store import ingest_batch
        from app.db.object_store import load_assignments
        from app.models.schemas import AssignmentIngest, IngestBatchRequest

        result = await ingest_batch(
            IngestBatchRequest(
                external_id="1001",
                name="CS-101",
                assignments=[
                    AssignmentIngest(
                        object_id="9001",
                        name="HW 3",
                        canonical_url="https://example.test/dropbox/9001",
                        due_at="2026-09-16T06:59:00.000Z",
                        submission_type="File",
                    ),
                ],
            ),
        )
        self.assertEqual(result.indexed_assignments, 1)
        objs = load_assignments(result.course_id)
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0].identifier, "hw:3")
        self.assertEqual(objs[0].due_at, "2026-09-16T06:59:00.000Z")
        self.assertEqual(objs[0].canonical_url, "https://example.test/dropbox/9001")

    async def test_xls_attachment_does_not_block_structured_assignment(self):
        import base64

        from app.db.chroma_store import ingest_batch
        from app.db.object_store import load_assignments
        from app.models.schemas import AssignmentAttachmentIngest, AssignmentIngest, IngestBatchRequest

        xls = base64.b64encode(b"PK\x03\x04excel-workbook").decode()
        result = await ingest_batch(
            IngestBatchRequest(
                external_id="1002",
                name="SIM-210",
                assignments=[
                    AssignmentIngest(
                        object_id="4",
                        name="HW3 initial",
                        canonical_url="https://example.test/dropbox/4",
                        due_at="2026-09-19T03:00:00.000Z",
                        submission_type="File",
                        attachments=[
                            AssignmentAttachmentIngest(
                                filename="hw2b_part2_data.xls",
                                file_type="xls",
                                content_base64=xls,
                            ),
                            AssignmentAttachmentIngest(
                                filename="hw3b.pdf",
                                file_type="pdf",
                                content_base64=xls,
                            ),
                        ],
                    ),
                ],
            ),
        )
        self.assertEqual(result.indexed_assignments, 1)
        objs = load_assignments(result.course_id)
        self.assertEqual(objs[0].name, "HW3 initial")
        self.assertEqual(objs[0].due_at, "2026-09-19T03:00:00.000Z")
        self.assertEqual(objs[0].identifier, "hw:3")



if __name__ == "__main__":
    unittest.main()
