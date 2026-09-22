"""Tests for bpe.shotgrid.versions — create_version & upload basics."""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

import pytest

from bpe.shotgrid.errors import ShotGridError
from bpe.shotgrid.versions import (
    create_version,
    list_shots_uploaded_by_user_on_date,
    list_versions_for_shot,
    upload_movie_to_version,
)
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


class TestListVersionsForShot:
    def test_includes_description(self) -> None:
        sg = MockShotgun()
        sg._add_entity(
            "Version",
            {
                "id": 501,
                "code": "E01_S01_0010_comp_v001",
                "user": {"type": "HumanUser", "id": 7, "name": "Test Artist"},
                "sg_status_list": "rev",
                "created_at": None,
                "image": None,
                "entity": {"type": "Shot", "id": 200},
                "description": "노트 한 줄\n//zeus.example/beluca/renders",
            },
        )
        rows = list_versions_for_shot(sg, 200, limit=10)
        assert len(rows) == 1
        assert rows[0]["code"] == "E01_S01_0010_comp_v001"
        assert rows[0]["description"] == "노트 한 줄\n//zeus.example/beluca/renders"
        assert rows[0]["version_id"] == 501

    def test_empty_description_key_when_missing(self) -> None:
        sg = MockShotgun()
        sg._add_entity(
            "Version",
            {
                "id": 502,
                "code": "E01_S01_0010_comp_v002",
                "user": {"type": "HumanUser", "id": 7, "name": "Test Artist"},
                "sg_status_list": "fin",
                "created_at": None,
                "image": None,
                "entity": {"type": "Shot", "id": 200},
            },
        )
        rows = list_versions_for_shot(sg, 200, limit=10)
        assert len(rows) == 1
        assert rows[0]["description"] == ""


class TestListShotsUploadedByUserOnDate:
    def test_dedupes_shot_and_returns_project(self) -> None:
        sg = MockShotgun()
        d = date(2026, 4, 1)
        sg._add_entity(
            "Version",
            {
                "id": 601,
                "user": {"type": "HumanUser", "id": 7},
                "created_at": datetime(2026, 4, 1, 15, 0, 0),
                "entity": {"type": "Shot", "id": 300, "code": "E01_S02"},
                "project": {"type": "Project", "id": 10, "name": "ProjA", "code": "PA"},
                "image": None,
                "sg_task": {"type": "Task", "id": 40},
                "description": "latest",
            },
        )
        sg._add_entity(
            "Version",
            {
                "id": 602,
                "user": {"type": "HumanUser", "id": 7},
                "created_at": datetime(2026, 4, 1, 10, 0, 0),
                "entity": {"type": "Shot", "id": 300, "code": "E01_S02"},
                "project": {"type": "Project", "id": 10, "name": "ProjA", "code": "PA"},
                "image": None,
                "sg_task": None,
                "description": "older",
            },
        )
        rows = list_shots_uploaded_by_user_on_date(sg, user_id=7, target_date=d)
        assert len(rows) == 1
        assert rows[0]["shot_id"] == 300
        assert rows[0]["shot_code"] == "E01_S02"
        assert rows[0]["project_id"] == 10
        assert rows[0]["project_name"] == "ProjA"
        assert rows[0]["default_task_id"] == 40
        assert rows[0]["version_description"] == "latest"

    def test_other_day_empty(self) -> None:
        sg = MockShotgun()
        sg._add_entity(
            "Version",
            {
                "id": 603,
                "user": {"type": "HumanUser", "id": 7},
                "created_at": datetime(2026, 4, 1, 12, 0, 0),
                "entity": {"type": "Shot", "id": 301, "code": "X"},
                "project": {"type": "Project", "id": 1, "name": "P"},
                "image": None,
                "description": "",
            },
        )
        rows = list_shots_uploaded_by_user_on_date(sg, user_id=7, target_date=date(2026, 4, 2))
        assert rows == []


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


# ── upload_movie_to_version: 로컬 임시 복사 시 원본 파일명 유지 ──────


class _RecordingSG(MockShotgun):
    """upload()에 넘어온 경로의 파일명·상위 폴더·존재 여부를 기록."""

    def __init__(self, fail_first: str = "") -> None:
        super().__init__()
        self.seen: List[Dict[str, Any]] = []
        self._fail_first = fail_first

    def upload(
        self,
        entity_type: str,
        entity_id: int,
        path: str,
        field_name: str = "sg_uploaded_movie",
        **kwargs: Any,
    ) -> int:
        p = Path(path)
        self.seen.append(
            {
                "name": p.name,
                "parent": p.parent.name,
                "exists": p.is_file(),
                "data": p.read_bytes() if p.is_file() else b"",
            }
        )
        if self._fail_first and len(self.seen) == 1:
            raise RuntimeError(self._fail_first)
        return super().upload(entity_type, entity_id, path, field_name, **kwargs)


@pytest.fixture()
def staging_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """로컬 임시 복사 강제 + tempfile 폴더·피드백 로그를 tmp_path로 격리."""
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setenv("BPE_SG_UPLOAD_ALWAYS_LOCAL_COPY", "1")
    monkeypatch.setenv("BPE_FEEDBACK_LOG_DIR", str(tmp_path / "fblog"))
    monkeypatch.setattr(tempfile, "tempdir", str(stage))
    return stage


def _make_movie(tmp_path: Path, name: str = "ep03_s003_0080_comp_v002.mov") -> Path:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    mov = src_dir / name
    mov.write_bytes(b"fake movie payload")
    return mov


class TestUploadMovieStaging:
    @pytest.mark.parametrize("with_progress", [False, True])
    def test_staged_upload_keeps_original_basename(
        self, tmp_path: Path, staging_env: Path, with_progress: bool
    ) -> None:
        mov = _make_movie(tmp_path)
        sg = _RecordingSG()
        sg._add_entity("Version", {"id": 50, "sg_uploaded_movie": None})
        fracs: List[float] = []
        cb = fracs.append if with_progress else None

        upload_movie_to_version(sg, 50, str(mov), progress_cb=cb)

        assert len(sg.seen) == 1
        seen = sg.seen[0]
        assert seen["name"] == mov.name
        assert seen["parent"].startswith("bpe_sg_upload_")
        assert seen["exists"] is True
        assert seen["data"] == mov.read_bytes()
        assert list(staging_env.iterdir()) == []
        assert mov.is_file()
        if with_progress:
            assert fracs and fracs[-1] == 1.0

    def test_staged_korean_basename(self, tmp_path: Path, staging_env: Path) -> None:
        mov = _make_movie(tmp_path, name="ep03_s003_0080_comp_v002_한글.mov")
        sg = _RecordingSG()
        sg._add_entity("Version", {"id": 54, "sg_uploaded_movie": None})

        upload_movie_to_version(sg, 54, str(mov))

        assert sg.seen[0]["name"] == mov.name
        assert list(staging_env.iterdir()) == []

    def test_staged_retry_reuses_copy_then_cleans_up(
        self, tmp_path: Path, staging_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bpe.shotgrid.versions as versions_mod

        monkeypatch.setattr(versions_mod.time, "sleep", lambda _s: None)
        mov = _make_movie(tmp_path)
        sg = _RecordingSG(fail_first="read timed out")
        sg._add_entity("Version", {"id": 51, "sg_uploaded_movie": None})

        upload_movie_to_version(sg, 51, str(mov))

        assert len(sg.seen) == 2
        assert all(s["exists"] and s["name"] == mov.name for s in sg.seen)
        assert list(staging_env.iterdir()) == []

    def test_staged_upload_failure_cleans_up(self, tmp_path: Path, staging_env: Path) -> None:
        mov = _make_movie(tmp_path)
        sg = _RecordingSG(fail_first="boom (non-retryable)")
        sg._add_entity("Version", {"id": 52, "sg_uploaded_movie": None})

        with pytest.raises(RuntimeError, match="boom"):
            upload_movie_to_version(sg, 52, str(mov))
        assert list(staging_env.iterdir()) == []

    def test_copy_failure_cleans_up(
        self, tmp_path: Path, staging_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import bpe.shotgrid.versions as versions_mod

        def _boom(*_a: Any, **_k: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(versions_mod.shutil, "copy2", _boom)
        mov = _make_movie(tmp_path)
        sg = _RecordingSG()
        sg._add_entity("Version", {"id": 53, "sg_uploaded_movie": None})

        with pytest.raises(ShotGridError, match="로컬 임시 폴더로 복사하지"):
            upload_movie_to_version(sg, 53, str(mov))
        assert sg.seen == []
        assert list(staging_env.iterdir()) == []
