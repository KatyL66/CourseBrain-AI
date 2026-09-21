"""Detect and filter low-value Brightspace navigation / boilerplate content."""

from __future__ import annotations

import re

# Definitive Brightspace page chrome markers
_DEFINITIVE_NAV_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Table of Contents\s*-\s*\d", re.I),
    re.compile(r"Notifications Account Settings Progress", re.I),
    re.compile(r"Clear Selection\s+Week\s+\d+", re.I),
    re.compile(r"All items selected\.?\s*Clear Selection", re.I),
    re.compile(r"Start Menu Start\s+\d", re.I),
    re.compile(r"My Grades Help Course Tools", re.I),
    re.compile(r"Log Out Home", re.I),
]

# Weaker markers — need multiple hits with low remaining text
_WEAK_NAV_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Access restricted before availability starts", re.I),
    re.compile(r"Access restricted after availability ends", re.I),
    re.compile(r"English \(United States\)", re.I),
    re.compile(r"Account Settings", re.I),
    re.compile(r"PDF document Updated", re.I),
    re.compile(r"Starts \w+ \d+, \d+ \d+:\d+ [AP]M", re.I),
]

# Brightspace Content availability chrome — visibility, not academic due dates.
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_AVAILABILITY_DATETIME = rf"{_MONTH}\s+\d{{1,2}},\s+\d{{4}}\s+\d{{1,2}}:\d{{2}}\s*[AP]M"
_AVAILABILITY_CHROME_PATTERNS: list[re.Pattern[str]] = [
    re.compile(rf"\bStarts\s+{_AVAILABILITY_DATETIME}", re.I),
    re.compile(rf"\bEnds\s+{_AVAILABILITY_DATETIME}", re.I),
    re.compile(rf"\bAvailable until\s+{_AVAILABILITY_DATETIME}", re.I),
    re.compile(r"Access restricted before availability starts\.?", re.I),
    re.compile(r"Access restricted after availability ends\.?", re.I),
]

MIN_SUBSTANTIVE_CHARS = 80


def strip_availability_chrome(text: str) -> str:
    """Remove Brightspace Starts/Ends/Available until chrome; keep academic due language."""
    if not text:
        return ""
    result = text
    for pat in _AVAILABILITY_CHROME_PATTERNS:
        result = pat.sub(" ", result)
    return re.sub(r"\s+", " ", result).strip()


def _strip_nav_markers(text: str) -> str:
    result = strip_availability_chrome(text)
    for pat in _DEFINITIVE_NAV_PATTERNS + _WEAK_NAV_PATTERNS:
        result = pat.sub(" ", result)
    result = re.sub(r"(?:Week\s+\d+\s*){3,}", " ", result, flags=re.I)
    result = re.sub(r"(?:PDF document\s*)+", " ", result, flags=re.I)
    return re.sub(r"\s+", " ", result).strip()


def is_navigation_boilerplate(text: str) -> bool:
    """Return True if text is likely Brightspace UI chrome, not course content."""
    if not text or not text.strip():
        return True

    text = text.strip()

    definitive_hits = sum(1 for p in _DEFINITIVE_NAV_PATTERNS if p.search(text))
    if definitive_hits >= 2:
        return True
    if definitive_hits >= 1 and re.search(r"Log Out Home", text, re.I):
        return True

    # Brightspace module listing pages: many "Week N" tokens dominate the text
    week_tokens = len(re.findall(r"\bWeek\s+\d+\b", text, re.I))
    words = text.split()
    if week_tokens >= 5 and week_tokens / max(len(words), 1) > 0.06:
        return True

    # Repeated course title in header (Brightspace duplicates title in nav chrome)
    title_matches = re.findall(
        r"\b[A-Z]{2,4}-\d{3}\b.*?(?:Engineering|Management|Physics)",
        text,
        re.I,
    )
    if len(title_matches) >= 2 and definitive_hits >= 1:
        return True

    weak_hits = sum(1 for p in _WEAK_NAV_PATTERNS if p.search(text))
    if weak_hits >= 2:
        if len(_strip_nav_markers(text)) < MIN_SUBSTANTIVE_CHARS * 2:
            return True

    if week_tokens >= 4 and week_tokens / max(len(words), 1) > 0.25:
        if len(_strip_nav_markers(text)) < MIN_SUBSTANTIVE_CHARS:
            return True

    return False


def filter_page_texts(page_texts: list[tuple[int | None, str]]) -> list[tuple[int | None, str]]:
    """Strip availability chrome, then drop page-level boilerplate before chunking."""
    cleaned: list[tuple[int | None, str]] = []
    for page, text in page_texts:
        stripped = strip_availability_chrome(text)
        if not is_navigation_boilerplate(stripped):
            cleaned.append((page, stripped))
    return cleaned
