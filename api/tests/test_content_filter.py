import unittest

from app.services.content_filter import (
    filter_page_texts,
    is_navigation_boilerplate,
    strip_availability_chrome,
)


NAV_HTML = (
    "Table of Contents - 20261_10010 NUM-201: Introduction to Numerical Methods "
    "Student Name Notifications Account Settings Progress English (United States) Log Out Home "
    "Announcements selected All items selected. Clear Selection Week 1 Week 2 References "
    "Week 3 Week 4 Week 5 Week 6 Week 7 Week 8 Week 9 Week 10"
)

LECTURE_PAGE = (
    "71 NUM-201 – Introduction to Numerical Methods. "
    "Newton's method finds a root of f(x) = 0 by iterating "
    "x_{n+1} = x_n - f(x_n)/f'(x_n) from an initial guess. "
    "First homework assignment • HW 1: Please read chapter 1 • Please write a "
    "summary of your learning (no more than 1 page), and submit it through Brightspace."
)

SYLLABUS_PAGE = (
    "Version of 8 June 2026 Syllabus for NUM-201, Introduction to Numerical Methods, "
    "page 7 of 14 Course Schedule: A Weekly Breakdown Date Tuesday "
    "Reading and homework assigned Homework due Week 15"
)


class ContentFilterTests(unittest.TestCase):
    def test_brightspace_navigation_detected(self):
        self.assertTrue(is_navigation_boilerplate(NAV_HTML))

    def test_lecture_content_preserved(self):
        self.assertFalse(is_navigation_boilerplate(LECTURE_PAGE))

    def test_syllabus_content_preserved(self):
        self.assertFalse(is_navigation_boilerplate(SYLLABUS_PAGE))

    def test_empty_text_is_boilerplate(self):
        self.assertTrue(is_navigation_boilerplate(""))
        self.assertTrue(is_navigation_boilerplate("   "))

    def test_strips_ends_availability_any_year(self):
        for year in ("2023", "2026", "2019"):
            text = f"lecture -- week 6 MS Project assignment Ends Dec 21, {year} 11:59 PM"
            cleaned = strip_availability_chrome(text)
            self.assertNotIn("Ends Dec 21", cleaned)
            self.assertNotIn(year, cleaned)
            self.assertIn("MS Project assignment", cleaned)

    def test_strips_starts_and_available_until(self):
        text = (
            "Starts Aug 21, 2023 12:00 AM Available until May 19, 2026 10:00 AM "
            "HW 9 (the decision-tree assignment)"
        )
        cleaned = strip_availability_chrome(text)
        self.assertNotIn("Starts", cleaned)
        self.assertNotIn("Available until", cleaned)
        self.assertIn("HW 9", cleaned)

    def test_keeps_academic_due_language(self):
        text = "HW 2 due September 9, 2026 11:59 PM. Homework due: 1-page summary."
        self.assertEqual(strip_availability_chrome(text), text)

    def test_keeps_assignment_due_phrase(self):
        text = "Assignment Due Apr 3, 2025 10:00 AM."
        self.assertIn("Assignment Due", strip_availability_chrome(text))

    def test_does_not_strip_lecture_ends_at(self):
        text = "The lecture ends at 5 PM in Hall 12."
        self.assertEqual(strip_availability_chrome(text), text)

    def test_mixed_chunk_keeps_assignment_due_drops_chrome(self):
        text = (
            "Access restricted before availability starts. "
            "Available until May 19, 2026 10:00 AM. HW 9 (the decision-tree assignment) "
            "Assignment Due Apr 3, 2025 10:00 AM."
        )
        cleaned = strip_availability_chrome(text)
        self.assertNotIn("Available until", cleaned)
        self.assertNotIn("Access restricted", cleaned)
        self.assertIn("HW 9", cleaned)
        self.assertIn("Assignment Due Apr 3, 2025 10:00 AM", cleaned)
        self.assertFalse(is_navigation_boilerplate(cleaned))

    def test_availability_only_page_dropped(self):
        text = "Starts Aug 21, 2023 12:00 AM Ends Dec 21, 2023 11:59 PM"
        filtered = filter_page_texts([(None, text)])
        self.assertEqual(filtered, [])

    def test_filter_page_texts_drops_nav(self):
        pages = [(None, NAV_HTML), (71, LECTURE_PAGE)]
        filtered = filter_page_texts(pages)
        self.assertEqual(filtered, [(71, LECTURE_PAGE)])


if __name__ == "__main__":
    unittest.main()
