"""Tests for bpe.shotgrid.versions — create_version & upload basics."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest

from bpe.shotgrid.errors import ShotGridError
from bpe.shotgrid.versions import create_version, upload_movie_to_version
from tests.shotgrid.mock_sg import MockShotgun

# ── create_version ───────────────────────────────────────────────────


class TestCreateVersion:
    def _sg(self) -> MockShotgun:
        sg = MockShotgun()
        sg._add_entity("Project", {"id": 100, "name": "TestProj"})
        sg._add_entity("Shot", {"id": 200, "code": "E01_S01_0010"})
        return sg

    def test_basic_create(self) -> None:
        sg = self._sg()
        result = create_version(
            sg,
            project_id=100,
            shot_id=200,
            task_id=None,
            version_name="E01_S01_0010_comp_v001",
        )
        assert result["type"] == "Version"
        assert "id" in result

    def test_with_task_and_artist(self) -> None:
        sg = self._sg()
        sg._add_entity("Task", {"id": 300, "content": "comp"})
        result = create_version(
            sg,
            project_id=100,
            shot_id=200,
            task_id=300,
            version_name="E01_S01_0010_comp_v002",
            artist_id=42,
            sg_status="rev",
        )
        assert result["type"] == "Version"

    def test_empty_name_raises(self) -> None:
        sg = self._sg()
        with pytest.raises(ShotGridError, match="Version Name"):
            create_version(sg, project_id=100, shot_id=200, task_id=None, version_name="")


# ── upload_movie_to_version ──────────────────────────────────────────


class TestUploadMovie:
    def test_missing_file_raises(self) -> None:
        sg = MockShotgun()
        with pytest.raises(ShotGridError, match="파일을 찾을 수 없습니다"):
            upload_movie_to_version(sg, 1, "/nonexistent/path.mov")

    def test_upload_small_local_file(self, tmp_path: object) -> None:
        """Upload a small local file (no staging needed)."""
        sg = MockShotgun()
        sg._add_entity("Version", {"id": 10, "sg_uploaded_movie": None})

        fd, path = tempfile.mkstemp(suffix=".mov")
        try:
            os.write(fd, b"fake movie data")
            os.close(fd)

            upload_movie_to_version(sg, 10, path)

            ver = sg.find_one("Version", [["id", "is", 10]], ["id", "sg_uploaded_movie"])
            assert ver is not None
            assert ver.get("sg_uploaded_movie") is not None
        finally:
            if os.path.isfile(path):
                os.unlink(path)

    def test_upload_returns_none_raises(self) -> None:
        """sg.upload() returning None must trigger ShotGridError."""

        class _NoneUploadSG(MockShotgun):
            def upload(self, *args: Any, **kwargs: Any) -> None:
                return None

        sg = _NoneUploadSG()
        sg._add_entity("Version", {"id": 20, "sg_uploaded_movie": None})

        fd, path = tempfile.mkstemp(suffix=".mov")
        try:
            os.write(fd, b"fake data")
            os.close(fd)
            with pytest.raises(ShotGridError, match="None을 반환"):
                upload_movie_to_version(sg, 20, path)
        finally:
            if os.path.isfile(path):
                os.unlink(path)

    def test_upload_field_empty_after_upload_raises(self) -> None:
        """sg.upload() returns an id but sg_uploaded_movie stays None."""

        class _NoFieldSG(MockShotgun):
            def upload(
                self,
                entity_type: str,
                entity_id: int,
                path: str,
                field_name: str = "sg_uploaded_movie",
                **kwargs: Any,
            ) -> int:
                return 999

        sg = _NoFieldSG()
        sg._add_entity("Version", {"id": 30, "sg_uploaded_movie": None})

        fd, path = tempfile.mkstemp(suffix=".mov")
        try:
            os.write(fd, b"fake data")
            os.close(fd)
            with pytest.raises(ShotGridError, match="sg_uploaded_movie 필드가 비어"):
                upload_movie_to_version(sg, 30, path)
        finally:
            if os.path.isfile(path):
                os.unlink(path)

    def test_upload_success_with_verification(self) -> None:
        """Full upload + verification passes when mock sets the field."""
        sg = MockShotgun()
        sg._add_entity("Version", {"id": 40, "sg_uploaded_movie": None})

        fd, path = tempfile.mkstemp(suffix=".mov")
        try:
            os.write(fd, b"real movie bytes")
            os.close(fd)

            upload_movie_to_version(sg, 40, path)

            ver = sg.find_one("Version", [["id", "is", 40]], ["id", "sg_uploaded_movie"])
            assert ver is not None
            mov = ver.get("sg_uploaded_movie")
            assert mov is not None
            assert isinstance(mov, dict)
            assert "url" in mov
        finally:
            if os.path.isfile(path):
                os.unlink(path)
