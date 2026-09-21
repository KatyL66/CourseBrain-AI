import unittest

from app.models.schemas import TopicIngest
from app.services.content_classifier import ContentType, classify_document


def _topic(**kwargs) -> TopicIngest:
    defaults = {
        "external_id": "1",
        "title": "Untitled",
        "url": "https://lms.example.edu/d2l/le/content/1001/viewContent/1/View",
    }
    defaults.update(kwargs)
    return TopicIngest(**defaults)


class ContentClassifierTests(unittest.TestCase):
    def test_syllabus_from_module(self):
        topic = _topic(
            title="CS-101 -- fall 2026",
            module_name="Syllabus",
            url="https://example.com/syllabus.pdf",
        )
        self.assertEqual(classify_document(topic), ContentType.SYLLABUS)

    def test_syllabus_from_title(self):
        topic = _topic(
            title="NUM-201 course syllabus",
            module_name="Content",
        )
        self.assertEqual(classify_document(topic), ContentType.SYLLABUS)

    def test_lecture_from_title(self):
        topic = _topic(
            title="lecture -- week 1",
            module_name="Content",
            url="https://example.com/lecture01.pdf",
        )
        self.assertEqual(classify_document(topic), ContentType.LECTURE)

    def test_lecture_week_three(self):
        topic = _topic(title="Week 3 Lecture", module_name="Content")
        self.assertEqual(classify_document(topic), ContentType.LECTURE)

    def test_lecture_project_management_lecture_week(self):
        topic = _topic(title="Project Management Lecture Week 1", module_name="Content")
        self.assertEqual(classify_document(topic), ContentType.LECTURE)

    def test_lecture_project_management_fundamentals(self):
        topic = _topic(title="Project Management Fundamentals", module_name="Content")
        self.assertEqual(classify_document(topic), ContentType.LECTURE)

    def test_assignment_homework(self):
        topic = _topic(
            title="HW 9 (the decision-tree assignment)",
            module_name="Content",
        )
        self.assertEqual(classify_document(topic), ContentType.ASSIGNMENT)

    def test_assignment_homework_one(self):
        topic = _topic(title="Homework 1", module_name="Content")
        self.assertEqual(classify_document(topic), ContentType.ASSIGNMENT)

    def test_assignment_workshop_week(self):
        topic = _topic(title="workshop -- week 1", module_name="Content")
        self.assertEqual(classify_document(topic), ContentType.ASSIGNMENT)

    def test_assignment_team_deliverable(self):
        topic = _topic(
            title="examples of team deliverable products",
            module_name="Content",
        )
        self.assertEqual(classify_document(topic), ContentType.ASSIGNMENT)

    def test_assignment_project_guidelines(self):
        topic = _topic(title="Project Guidelines", module_name="Content")
        self.assertEqual(classify_document(topic), ContentType.ASSIGNMENT)

    def test_assignment_final_project_instructions(self):
        topic = _topic(title="Final Project Instructions", module_name="Content")
        self.assertEqual(classify_document(topic), ContentType.ASSIGNMENT)

    def test_assignment_ms_project(self):
        topic = _topic(title="MS Project assignment", module_name="Content")
        self.assertEqual(classify_document(topic), ContentType.ASSIGNMENT)

    def test_announcement(self):
        topic = _topic(
            title="Important update",
            module_name="Announcements",
        )
        self.assertEqual(classify_document(topic), ContentType.ANNOUNCEMENT)

    def test_other_references(self):
        topic = _topic(title="references", module_name="Content")
        self.assertEqual(classify_document(topic), ContentType.OTHER)

    def test_other_references_and_reading(self):
        topic = _topic(title="references and additional reading", module_name="Content")
        self.assertEqual(classify_document(topic), ContentType.OTHER)

    def test_syllabus_wins_over_project_keyword(self):
        topic = _topic(
            title="CS-101 -- syllabus -- team project policy",
            module_name="Syllabus",
        )
        self.assertEqual(classify_document(topic), ContentType.SYLLABUS)

    def test_overview_title_alone_is_not_syllabus(self):
        topic = _topic(
            title="Overview",
            module_name="Overview",
            content="<p>Welcome to SIM-210. Please check Announcements each week.</p>",
        )
        self.assertEqual(classify_document(topic), ContentType.OTHER)

    def test_overview_with_course_grading_is_syllabus(self):
        topic = _topic(
            title="Overview",
            module_name="Overview",
            content=(
                "<h2>Grading</h2><p>Homework: 80 points of the total course grade. "
                "Project: 150 points. Exams: 170 points.</p>"
            ),
        )
        self.assertEqual(classify_document(topic), ContentType.SYLLABUS)

    def test_grading_policies_pdf_is_syllabus(self):
        topic = _topic(
            title="Grading Policies",
            module_name="Content",
            url="https://example.com/grading.pdf",
        )
        self.assertEqual(classify_document(topic), ContentType.SYLLABUS)

    def test_project_description_stays_assignment(self):
        topic = _topic(
            title="Project Description",
            module_name="Project",
            content=(
                "Peer Review 12 points. Report - Part I (Activities 1,2,3) 25 points. "
                "Report - Part II 25 points. Partner Evaluation 12 points. "
                "All members will receive the same grade."
            ),
        )
        self.assertEqual(classify_document(topic), ContentType.ASSIGNMENT)

    def test_course_schedule_title_is_not_automatically_syllabus(self):
        topic = _topic(
            title="SIM-210 Course Schedule",
            module_name="Getting Started > Course Schedule",
            content="<p>Week 1: Introduction. Week 2: Queuing.</p>",
        )
        self.assertEqual(classify_document(topic), ContentType.OTHER)

    def test_lecture_overview_week_stays_lecture(self):
        topic = _topic(
            title="Project Management Overview Week 1",
            module_name="Content",
        )
        self.assertEqual(classify_document(topic), ContentType.LECTURE)


if __name__ == "__main__":
    unittest.main()
