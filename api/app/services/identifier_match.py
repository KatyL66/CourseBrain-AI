"""Extract and match course identifiers (HW1, Quiz 2, Project 3, etc.)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# kind, pattern with one capture group for the number (or none for fixed names)
# Use (?=\D|$) instead of trailing \b so compact forms (lab2, hw1) work before CJK text.
_IDENTIFIER_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("hw", re.compile(r"(?<![a-zA-Z])(?:hw|homework)\s*#?\s*(\d+)(?=\D|$)", re.I)),
    ("hw", re.compile(r"(?<![a-zA-Z])(?:hw|homework)(\d+)(?=\D|$)", re.I)),
    ("hw", re.compile(r"作业\s*#?\s*(\d+)")),
    ("lab", re.compile(r"(?<![a-zA-Z])lab\s*#?\s*(\d+)(?=\D|$)", re.I)),
    ("lab", re.compile(r"(?<![a-zA-Z])lab(\d+)(?=\D|$)", re.I)),
    ("assignment", re.compile(r"\bassignment\s*#?\s*(\d+)(?=\D|$)", re.I)),
    ("lecture", re.compile(r"(?<![a-zA-Z])lecture\s*#?\s*(\d+[a-z]?)(?=\D|$)", re.I)),
    ("quiz", re.compile(r"\bquiz\s*#?\s*(\d+)(?=\D|$)", re.I)),
    ("project", re.compile(r"\bproject\s*#?\s*(\d+)(?=\D|$)", re.I)),
    ("midterm", re.compile(r"\bmidterm\s*#?\s*(\d+)(?=\D|$)", re.I)),
    ("chapter", re.compile(r"\b(?:chapter|ch\.?)\s*#?\s*(\d+)(?=\D|$)", re.I)),
    ("week", re.compile(r"\bweek\s*#?\s*(\d+)(?=\D|$)", re.I)),
]

# Fixed-name identifiers (no number)
_NAMED_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("final_exam", re.compile(r"\bfinal\s+exam\b", re.I)),
    ("midterm", re.compile(r"\bmidterm\b", re.I)),
]

IDENTIFIER_MATCH_BOOST = 0.15


@dataclass(frozen=True)
class CourseIdentifier:
    kind: str
    number: int | None = None

    @property
    def key(self) -> str:
        if self.number is not None:
            return f"{self.kind}:{self.number}"
        return self.kind


def extract_identifiers(text: str) -> list[CourseIdentifier]:
    """Extract normalized course identifiers from text."""
    if not text:
        return []

    found: list[CourseIdentifier] = []
    seen: set[str] = set()

    for kind, pattern in _IDENTIFIER_RULES:
        for match in pattern.finditer(text):
            number = int(match.group(1))
            ident = CourseIdentifier(kind=kind, number=number)
            if ident.key not in seen:
                seen.add(ident.key)
                found.append(ident)

    for kind, pattern in _NAMED_RULES:
        if pattern.search(text):
            ident = CourseIdentifier(kind=kind)
            if ident.key not in seen:
                seen.add(ident.key)
                found.append(ident)

    return found


_HW_KINDS = frozenset({"hw", "assignment"})


def identifiers_match(a: CourseIdentifier, b: CourseIdentifier) -> bool:
    if a.key == b.key:
        return True
    if (
        a.number is not None
        and a.number == b.number
        and a.kind in _HW_KINDS
        and b.kind in _HW_KINDS
    ):
        return True
    return False


def text_matches_any_identifier(text: str, targets: list[CourseIdentifier]) -> bool:
    if not targets or not text:
        return False
    for candidate in extract_identifiers(text):
        for target in targets:
            if identifiers_match(candidate, target):
                return True
    return False


def collect_query_identifiers(question: str, *extra_queries: str) -> list[CourseIdentifier]:
    """Union identifiers from the user question and planner search queries."""
    seen: set[str] = set()
    result: list[CourseIdentifier] = []
    for text in (question, *extra_queries):
        for ident in extract_identifiers(text):
            if ident.key not in seen:
                seen.add(ident.key)
                result.append(ident)
    return result


def identifier_boost(text: str, query_identifiers: list[CourseIdentifier]) -> float:
    """Boost when chunk text explicitly mentions the same identifier as the query."""
    if not query_identifiers:
        return 0.0
    if text_matches_any_identifier(text, query_identifiers):
        return IDENTIFIER_MATCH_BOOST
    return 0.0
