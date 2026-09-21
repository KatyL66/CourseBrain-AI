import unittest

from app.services.identifier_match import (
    CourseIdentifier,
    collect_query_identifiers,
    extract_identifiers,
    identifier_boost,
    text_matches_any_identifier,
)


class IdentifierExtractTests(unittest.TestCase):
    def test_hw1_variants_normalize(self):
        for text in ("HW1", "HW 1", "Homework 1", "hw1 是啥", "HW 1:", "作业1"):
            ids = extract_identifiers(text)
            self.assertTrue(any(i.key == "hw:1" for i in ids), msg=text)

    def test_hw_matches_assignment_kind(self):
        from app.services.identifier_match import CourseIdentifier, identifiers_match

        hw = CourseIdentifier(kind="hw", number=3)
        assignment = CourseIdentifier(kind="assignment", number=3)
        self.assertTrue(identifiers_match(hw, assignment))

    def test_lab2_variants(self):
        for text in ("lab2", "Lab 2", "lab #2", "LAB #2", "lab2是要干啥"):
            ids = extract_identifiers(text)
            self.assertTrue(any(i.key == "lab:2" for i in ids), msg=text)

    def test_lab2_in_chunk_text(self):
        chunk = "Page 1 of 5 LAB #2 Gauss's Law, Symmetry Models, and Graphical Analysis"
        targets = extract_identifiers("lab2 objective")
        self.assertTrue(text_matches_any_identifier(chunk, targets))

    def test_project_numbered(self):
        self.assertEqual(extract_identifiers("Project 3 requirements")[0].key, "project:3")

    def test_team_project_not_numbered_hw(self):
        ids = extract_identifiers("team project 是啥")
        self.assertFalse(any(i.kind == "hw" for i in ids))

    def test_chunk_matches_hw1(self):
        chunk = "First homework assignment • HW 1: Please read chapter 1"
        targets = extract_identifiers("hw1 是啥")
        self.assertTrue(text_matches_any_identifier(chunk, targets))

    def test_generic_project_does_not_match_hw1(self):
        chunk = "Your project is to prepare systems engineering diagrams"
        targets = extract_identifiers("hw1 是啥")
        self.assertFalse(text_matches_any_identifier(chunk, targets))

    def test_collect_from_question_and_planner_queries(self):
        ids = collect_query_identifiers("hw1 是啥", "HW1 assignment details", "HW1 requirements")
        self.assertEqual([i.key for i in ids], ["hw:1"])

    def test_identifier_boost(self):
        targets = collect_query_identifiers("hw1 是啥")
        boost = identifier_boost("HW 1: 1-page summary", targets)
        self.assertGreater(boost, 0.0)
        self.assertEqual(identifier_boost("team project overview", targets), 0.0)


if __name__ == "__main__":
    unittest.main()
