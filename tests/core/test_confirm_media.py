"""Tests for bpe.core.confirm_media — 샷 폴더에서 재료 찾기(가짜 폴더만 사용)."""

from __future__ import annotations

from pathlib import Path

from bpe.core.confirm_media import (
    find_edit,
    find_org,
    find_shot_media,
    find_versions,
    is_lut_baked,
    parse_version,
    shot_root_from_movie,
)


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def test_parse_version() -> None:
    assert parse_version("E105_S023_0390_comp_v017.mov") == 17
    assert parse_version("yego_0010_comp_v001_lut.mov") == 1
    assert parse_version("v002") == 2
    assert parse_version("no_version.mov") is None
    assert parse_version("river_view.mov") is None


def test_is_lut_baked() -> None:
    assert is_lut_baked("yego_0010_comp_v001_lut.mov")
    assert not is_lut_baked("yego_0010_comp_v001.mov")
    assert not is_lut_baked("absolute_v001.mov")


def test_shot_root_from_movie_both_layouts(tmp_path: Path) -> None:
    shot = tmp_path / "04_sq" / "E105" / "E105_S023_0390"
    internal = shot / "comp" / "devl" / "renders" / "E105_S023_0390_comp_v017.mov"
    vendor = shot / "comp" / "v002" / "E105_S023_0390_comp_v002.mov"
    assert shot_root_from_movie(internal) == shot
    assert shot_root_from_movie(vendor) == shot
    assert shot_root_from_movie(tmp_path / "loose.mov") is None


def test_internal_layout_finds_everything(tmp_path: Path) -> None:
    shot = tmp_path / "SHOT_A"
    r = shot / "comp" / "devl" / "renders"
    v15 = _touch(r / "SHOT_A_comp_v015.mov")
    v16 = _touch(r / "SHOT_A_comp_v016.mov")
    v17 = _touch(r / "SHOT_A_comp_v017.mov")
    (r / "SHOT_A_comp_v017").mkdir()  # 같은 이름의 폴더가 있어도 무시
    org = _touch(shot / "plate" / "org" / "v001" / "mov" / "SHOT_A_org_v001.mov")
    edit = _touch(shot / "edit" / "SHOT_A_edit_v001.mov")

    media = find_shot_media(v17)
    assert media.shot_root == shot
    assert media.current is not None and media.current.path == v17
    assert media.previous is not None and media.previous.path == v16
    assert [v.version for v in media.versions] == [15, 16, 17]
    assert media.versions[0].path == v15
    assert media.org == org
    assert media.edit == edit


def test_vendor_layout_prefers_non_lut(tmp_path: Path) -> None:
    shot = tmp_path / "yego_0010"
    plain1 = _touch(shot / "comp" / "v001" / "yego_0010_comp_v001.mov")
    _touch(shot / "comp" / "v001" / "yego_0010_comp_v001_lut.mov")
    plain2 = _touch(shot / "comp" / "v002" / "yego_0010_comp_v002.mov")
    org = _touch(shot / "plate" / "org" / "v001" / "yego_0010_org_v001.mov")

    versions = find_versions(shot)
    assert [(v.version, v.path, v.has_lut_baked) for v in versions] == [
        (1, plain1, False),
        (2, plain2, False),
    ]
    media = find_shot_media(plain2)
    assert media.previous is not None and media.previous.path == plain1
    assert media.org == org
    assert media.edit is None


def test_only_lut_version_is_kept_and_flagged(tmp_path: Path) -> None:
    shot = tmp_path / "S"
    lut = _touch(shot / "comp" / "v003" / "S_comp_v003_lut.mov")
    media = find_shot_media(lut)
    assert media.current is not None and media.current.has_lut_baked
    assert media.previous is None


def test_first_version_has_no_previous(tmp_path: Path) -> None:
    shot = tmp_path / "S"
    v1 = _touch(shot / "comp" / "devl" / "renders" / "S_comp_v001.mov")
    media = find_shot_media(v1)
    assert media.previous is None
    assert media.org is None and media.edit is None


def test_latest_plate_and_edit_version_wins(tmp_path: Path) -> None:
    shot = tmp_path / "S"
    _touch(shot / "plate" / "org" / "v001" / "mov" / "S_org_v001.mov")
    new_org = _touch(shot / "plate" / "org" / "v002" / "mov" / "S_org_v002.mov")
    _touch(shot / "edit" / "v001" / "S_edit_v001.mov")
    new_edit = _touch(shot / "edit" / "v002" / "S_edit_v002.mov")
    assert find_org(shot) == new_org
    assert find_edit(shot) == new_edit


def test_movie_outside_shot_folder(tmp_path: Path) -> None:
    loose = _touch(tmp_path / "clip_v003.mov")
    media = find_shot_media(loose)
    assert media.shot_root is None
    assert media.current is not None and media.current.version == 3
    assert media.versions == [media.current]
