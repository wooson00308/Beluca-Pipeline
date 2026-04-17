"""Tests for bpe.shotgrid.notes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from bpe.shotgrid.errors import ShotGridError
from bpe.shotgrid.notes import (
    build_native_style_note_subject,
    create_note,
    create_note_with_result,
    list_notes_for_project,
    list_notes_for_shots,
    note_addressings_from_assignees,
)
from tests.shotgrid.mock_sg import MockShotgun


def _make_note(
    sg: MockShotgun,
    note_id: int,
    shot_id: int,
    *,
    subject: str = "Review",
    content: str = "Looks good",
    author_name: str = "Alice",
    project_id: int = 100,
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
            "project": {"type": "Project", "id": project_id, "name": project_name},
        },
    )


class TestListNotesForProject:
    def test_empty_project_id(self) -> None:
        sg = MockShotgun()
        assert list_notes_for_project(sg, 0) == []

    def test_filters_by_project(self) -> None:
        sg = MockShotgun()
        _make_note(sg, 1, 10, project_id=5, project_name="P5", subject="A")
        _make_note(sg, 2, 20, project_id=6, project_name="P6", subject="B")

        result = list_notes_for_project(sg, 5, days_back=0)

        assert len(result) == 1
        assert result[0]["note_id"] == 1
        assert result[0]["subject"] == "A"
        assert result[0]["project_name"] == "P5"


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
        assert result[0]["shot_ids"] == [10]
        assert result[1]["shot_ids"] == [20]

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
                "note_links": [{"type": "Shot", "id": 1}],
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
        assert note["shot_ids"] == [1]

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


class TestGetNoteAttachments:
    def test_returns_image_attachments_for_note(self) -> None:
        from bpe.shotgrid.notes import get_note_attachments

        sg = MockShotgun()
        sg._add_entity(
            "Attachment",
            {
                "id": 10,
                "filename": "frame.png",
                "this_file": {"url": "https://example.com/frame.png", "name": "frame.png"},
                "attachment_links": [{"type": "Note", "id": 7, "name": "Note7"}],
            },
        )
        result = get_note_attachments(sg, 7)
        assert len(result) == 1
        assert result[0]["att_id"] == 10
        assert result[0]["url"] == "https://example.com/frame.png"

    def test_filters_non_image_attachments(self) -> None:
        from bpe.shotgrid.notes import get_note_attachments

        sg = MockShotgun()
        sg._add_entity(
            "Attachment",
            {
                "id": 11,
                "filename": "brief.pdf",
                "this_file": {"url": "https://example.com/brief.pdf"},
                "attachment_links": [{"type": "Note", "id": 8, "name": "N8"}],
            },
        )
        assert get_note_attachments(sg, 8) == []

    def test_fallback_skips_when_note_field_missing_on_schema(self) -> None:
        """Sites without Attachment.note should not treat API 103 as fatal warning."""

        from bpe.shotgrid.notes import get_note_attachments

        class SiteWithoutNoteField:
            def find(self, entity_type: str, filters: Any, fields: Any, **kwargs: Any) -> List[Any]:
                fs = str(filters)
                if "attachment_links" in fs:
                    return []
                if "note" in fs and "Note" in fs:
                    raise RuntimeError(
                        "API read() Attachment.note doesn't exist: "
                        '{"path" => "note", "relation" => "is", ...}'
                    )
                return []

        assert get_note_attachments(SiteWithoutNoteField(), 999) == []


class TestBuildNativeStyleNoteSubject:
    def test_with_version_and_shot(self) -> None:
        s = build_native_style_note_subject("Alice Kim", "S010_v003", "SH010")
        assert s == "Alice Kim's Note on S010_v003 and SH010"

    def test_without_version(self) -> None:
        s = build_native_style_note_subject("Bob", None, "SH020")
        assert s == "Bob's Note on SH020"

    def test_blank_author_uses_user(self) -> None:
        s = build_native_style_note_subject("", None, "SH030")
        assert s == "User's Note on SH030"


class TestNoteAddressingsFromAssignees:
    def test_extracts_human_users(self) -> None:
        raw = [
            {"type": "HumanUser", "id": 10, "name": "A"},
            {"type": "Group", "id": 2},
            "bad",
        ]
        assert note_addressings_from_assignees(raw) == [{"type": "HumanUser", "id": 10}]

    def test_empty(self) -> None:
        assert note_addressings_from_assignees([]) == []
        assert note_addressings_from_assignees(None) == []


class TestCreateNote:
    def test_create_note_minimal(self) -> None:
        sg = MockShotgun()
        sg._add_entity("Project", {"id": 1, "code": "P1"})
        note = create_note(
            sg,
            project_id=1,
            shot_id=50,
            subject="Hello",
            content="Body text",
        )
        assert note.get("type") == "Note"
        nid = note.get("id")
        assert nid is not None
        pool = sg._entities.get("Note", [])
        assert len(pool) == 1
        row = pool[0]
        assert row.get("subject") == "Hello"
        assert row.get("content") == "Body text"
        assert row.get("note_links") == [{"type": "Shot", "id": 50}]

    def test_create_note_with_author_and_addressings(self) -> None:
        sg = MockShotgun()
        sg._add_entity("Project", {"id": 1})
        author = {"type": "HumanUser", "id": 7, "login": "me"}
        addr = [{"type": "HumanUser", "id": 8}]
        note = create_note(
            sg,
            project_id=1,
            shot_id=50,
            subject="H",
            content="B",
            author_user=author,
            addressings_to=addr,
        )
        nid = note["id"]
        row = next(e for e in sg._entities["Note"] if e["id"] == nid)
        assert row.get("user") == {"type": "HumanUser", "id": 7}
        assert row.get("addressings_to") == addr
        assert row.get("addressings_cc") == addr

    def test_create_note_explicit_cc_differs_from_to(self) -> None:
        sg = MockShotgun()
        sg._add_entity("Project", {"id": 1})
        to = [{"type": "HumanUser", "id": 8}]
        cc = [{"type": "HumanUser", "id": 9}]
        note = create_note(
            sg,
            project_id=1,
            shot_id=50,
            subject="H",
            content="B",
            addressings_to=to,
            addressings_cc=cc,
        )
        nid = note["id"]
        row = next(e for e in sg._entities["Note"] if e["id"] == nid)
        assert row.get("addressings_to") == to
        assert row.get("addressings_cc") == cc

    def test_create_note_upload_fallback_after_attachments_fails(self, tmp_path) -> None:
        """attachments 전략만 실패할 때 field 없이 업로드로 성공하는지."""

        try:
            from shotgun_api3 import ShotgunError as _SGErr
        except ImportError:
            _SGErr = RuntimeError  # pragma: no cover

        class AttachmentsFail(MockShotgun):
            def upload(
                self,
                entity_type: str,
                entity_id: int,
                path: str,
                field_name: str = "sg_uploaded_movie",
                **kwargs: Any,
            ) -> int:
                if entity_type == "Note" and field_name == "attachments":
                    raise _SGErr("simulated attachments fail")
                return super().upload(entity_type, entity_id, path, field_name, **kwargs)

        sg = AttachmentsFail()
        sg._add_entity("Project", {"id": 1})
        png = tmp_path / "x.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        res = create_note_with_result(
            sg,
            project_id=1,
            shot_id=50,
            subject="S",
            content="C",
            attachment_path=str(png),
        )
        assert res.attachment_ok is True
        assert res.note.get("type") == "Note"

    def test_create_note_with_version_and_attachment(self, tmp_path) -> None:
        sg = MockShotgun()
        sg._add_entity("Project", {"id": 1})
        png = tmp_path / "x.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        note = create_note(
            sg,
            project_id=1,
            shot_id=50,
            subject="S",
            content="C",
            version_id=99,
            attachment_path=str(png),
        )
        nid = note["id"]
        row = next(e for e in sg._entities["Note"] if e["id"] == nid)
        links = row.get("note_links") or []
        assert {"type": "Shot", "id": 50} in links
        assert {"type": "Version", "id": 99} in links
        assert "attachments" in row

    def test_create_note_raises_shotgrid_error(self) -> None:
        class Boom:
            def create(self, *a, **k):
                raise RuntimeError("nope")

            def upload(self, *a, **k):
                pass

        with pytest.raises(ShotGridError, match="Note 생성 실패"):
            create_note(
                Boom(),
                project_id=1,
                shot_id=1,
                subject="x",
                content="y",
            )

    def test_create_note_with_result_multiple_attachment_paths(self, tmp_path) -> None:
        """한 노트에 attachment_paths로 여러 PNG를 순서대로 업로드한다."""

        class CountUpload(MockShotgun):
            def __init__(self) -> None:
                super().__init__()
                self.upload_calls = 0

            def upload(self, *a: Any, **kw: Any) -> int:
                self.upload_calls += 1
                return super().upload(*a, **kw)

        sg = CountUpload()
        sg._add_entity("Project", {"id": 1})
        paths = []
        for i in (1, 2):
            p = tmp_path / f"m{i}.png"
            p.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([i]) * 16)
            paths.append(str(p))
        res = create_note_with_result(
            sg,
            project_id=1,
            shot_id=50,
            subject="S",
            content="C",
            attachment_paths=paths,
        )
        assert res.attachment_requested is True
        assert res.attachment_ok is True
        assert sg.upload_calls == 2

    def test_create_note_with_result_attachment_failure(self, tmp_path) -> None:
        class UploadFail(MockShotgun):
            def upload(self, *a: Any, **k: Any) -> int:
                raise RuntimeError("upload dead")

        sg = UploadFail()
        sg._add_entity("Project", {"id": 1})
        png = tmp_path / "x.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        res = create_note_with_result(
            sg,
            project_id=1,
            shot_id=50,
            subject="S",
            content="C",
            attachment_path=str(png),
        )
        assert res.attachment_requested is True
        assert res.attachment_ok is False
        assert res.attachment_error is not None
        assert res.note.get("type") == "Note"
