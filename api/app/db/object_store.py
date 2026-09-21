"""Lightweight per-course JSON store for structured Brightspace objects."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from app.config import settings


@dataclass
class AssignmentObject:
    object_id: str
    name: str
    canonical_url: str
    source_type: str = "assignment"
    identifier: str | None = None
    due_at: str | None = None
    submission_type: str | None = None


def _objects_file(course_id: UUID) -> Path:
    path = Path(settings.data_dir) / "objects"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{course_id}.json"


def assignments_store_exists(course_id: UUID) -> bool:
    """True when this course has completed an Assignments ingest (even if empty)."""
    return (Path(settings.data_dir) / "objects" / f"{course_id}.json").exists()


def load_assignments(course_id: UUID) -> list[AssignmentObject]:
    file = _objects_file(course_id)
    if not file.exists():
        return []
    data = json.loads(file.read_text())
    return [AssignmentObject(**row) for row in data.get("assignments", [])]


def save_assignments(course_id: UUID, assignments: list[AssignmentObject]) -> None:
    file = _objects_file(course_id)
    payload = {"assignments": [asdict(item) for item in assignments]}
    file.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def assignment_topic_id(object_id: str) -> str:
    return f"assignment:{object_id}"
