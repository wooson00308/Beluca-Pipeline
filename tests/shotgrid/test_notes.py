"""Tests for bpe.shotgrid.notes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from bpe.shotgrid.notes import list_notes_for_shots
from tests.shotgrid.mock_sg import MockShotgun


def _make_note(
    sg: MockShotgun,
    note_id: int,
    shot_id: int,
    *,
    subject: str = "Review",
    content: str = "Looks good",
    author_name: str = "Alice",
    project_name: str = "ProjectA",
    shot_name: str = "SH010",
    created_at: Any = None,
) -> Dict[str, Any]:
    if created_at is None:
        created_at = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
    return sg._add_entity(
        "Note",
        {
            "id": note_id,
            "subject": subject,
            "content": content,
            "created_at": created_at,
            "created_by": {"type": "HumanUser", "id": 1, "name": author_name},
            "note_links": [{"type": "Shot", "id": shot_id, "name": shot_name}],
            "project": {"type": "Project", "id": 100, "name": project_name},
        },
    )


class TestListNotesForShots:
    def test_empty_shot_ids(self) -> None:
        sg = MockShotgun()
        assert list_notes_for_shots(sg, []) == []

    def test_returns_formatted_notes(self) -> None:
        sg = MockShotgun()
        _make_note(sg, 1, 10, subject="First", content="Body1", shot_name="SH010")
        _make_note(sg, 2, 20, subject="Second", content="Body2", shot_name="SH020")

        result = list_notes_for_shots(sg, [10, 20], days_back=0)

        assert len(result) == 2
        assert result[0]["note_id"] == 1
        assert result[0]["subject"] == "First"
        assert result[0]["content"] == "Body1"
        assert result[0]["context"] == "SH010"
        assert result[0]["author"] == "Alice"
        assert result[0]["project_name"] == "ProjectA"
        assert result[0]["timestamp"] == "2026-03-20 12:00"

    def test_missing_fields_default(self) -> None:
        sg = MockShotgun()
        sg._add_entity(
            "Note",
            {
                "id": 99,
                "subject": None,
                "content": None,
                "created_at": None,
                "created_by": None,
                "note_links": None,
                "project": None,
            },
        )

        result = list_notes_for_shots(sg, [1], days_back=0)
        assert len(result) == 1
        note = result[0]
        assert note["subject"] == ""
        assert note["content"] == ""
        assert note["author"] == "—"
        assert note["context"] == "—"
        assert note["project_name"] == "—"

    def test_no_days_back_returns_all(self) -> None:
        sg = MockShotgun()
        _make_note(
            sg,
            1,
            10,
            created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )

        result = list_notes_for_shots(sg, [10], days_back=0)
        assert len(result) == 1

    def test_raises_shotgrid_error_on_total_failure(self) -> None:
        """Both primary and fallback queries fail → ShotGridError."""

        class BrokenSG:
            def find(self, *a: Any, **kw: Any) -> List[Any]:
                raise RuntimeError("boom")

        from bpe.shotgrid.errors import ShotGridError

        with pytest.raises(ShotGridError, match="노트 조회 실패"):
            list_notes_for_shots(BrokenSG(), [1], days_back=0)
