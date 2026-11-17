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
    quick_version_movie,
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


def test_precomp_and_other_task_folders_find_the_shot(tmp_path: Path) -> None:
    shot = tmp_path / "ep04" / "ep04_s003_0120"
    pre1 = _touch(shot / "precomp" / "v001" / "ep04_s003_0120_precomp_v001.mov")
    pre2 = _touch(shot / "precomp" / "v002" / "ep04_s003_0120_precomp_v002.mov")
    _touch(shot / "comp" / "v005" / "ep04_s003_0120_comp_v005.mov")  # 다른 작업의 버전은 안 섞임
    org = _touch(shot / "plate" / "org" / "v001" / "hi" / "ep04_s003_0120_org_v001.mov")
    edit = _touch(shot / "edit" / "ep04_s003_0120_edit_v001.mov")
    assert shot_root_from_movie(pre2) == shot
    media = find_shot_media(pre2)
    assert media.org == org and media.edit == edit
    assert [v.path for v in media.versions] == [pre1, pre2]
    assert media.previous is not None and media.previous.path == pre1
    # 이름을 모르는 작업 폴더: plate·edit 가 있는 위쪽 폴더가 샷 폴더
    fx = _touch(shot / "fx" / "v003" / "ep04_s003_0120_fx_v003.mov")
    assert shot_root_from_movie(fx) == shot
    assert find_shot_media(fx).org == org


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


def test_plate_movie_is_found_in_hi_or_any_other_subfolder(tmp_path: Path) -> None:
    shot = tmp_path / "ep06_s043_0150"
    org = shot / "plate" / "org"
    (org / "v001" / "mov").mkdir(parents=True)
    (org / "v002" / "mov").mkdir(parents=True)
    (org / "v002" / "lo").mkdir(parents=True)
    _touch(org / "v001" / "hi" / "ep06_s043_0150_org_v001.mov")
    hi = _touch(org / "v002" / "hi" / "ep06_s043_0150_org_v002.mov")
    assert find_org(shot) == hi  # mov 폴더가 비어 있으면 hi 를 본다, 최신 버전 우선

    other = tmp_path / "s2"
    odd = _touch(other / "plate" / "org" / "v001" / "prores" / "s2_org_v001.mov")
    assert find_org(other) == odd  # 처음 보는 이름의 폴더도 찾아본다

    both = tmp_path / "s3"
    _touch(both / "plate" / "org" / "v001" / "hi" / "s3_org_v001.mov")
    mov = _touch(both / "plate" / "org" / "v001" / "mov" / "s3_org_v001.mov")
    assert find_org(both) == mov  # 둘 다 있으면 mov 가 먼저


def test_quick_version_movie_goes_straight_to_the_usual_place(tmp_path: Path) -> None:
    shot = tmp_path / "PROJ_001" / "04_sq" / "ep06" / "ep06_s020_0012"
    lut = _touch(shot / "comp" / "devl" / "renders" / "ep06_s020_0012_comp_v001_lut.mov")
    _touch(shot / "comp" / "devl" / "renders" / "ep06_s020_0012_comp_v001.mov")
    pre = _touch(shot / "precomp" / "v002" / "ep06_s020_0012_precomp_v002.mov")
    root = str(tmp_path)

    def quick(version: str, tasks: tuple = ("comp", "precomp")) -> object:
        return quick_version_movie(root, "PROJ_001", "ep06_s020_0012", version, tasks)

    assert quick("EP06_S020_0012_comp_v001_lut") == lut  # 이름이 똑같은 영상만
    assert quick("ep06_s020_0012_precomp_v002", ("", "comp", "comp", "precomp")) == pre
    assert quick("ep06_s020_0012_comp_v009") is None  # 없으면 넓게 찾기로 넘어감
    assert quick("") is None
    assert quick_version_movie(root, "PROJ_001", "ep99_s001_0010", "x_v001") is None
    assert quick_version_movie("", "PROJ_001", "ep06_s020_0012", "x_v001") is None


def test_twin_version_key_ignores_lut_suffix_and_case() -> None:
    from bpe.core.confirm_media import twin_version_key

    a = twin_version_key("ep08_s014_0040_comp_v003")
    assert a == twin_version_key("EP08_s014_0040_comp_v003_lut")
    assert a == twin_version_key("ep08_s014_0040_comp_v003_LUT.mov")
    assert a != twin_version_key("ep08_s014_0040_comp_v002_lut")
    assert twin_version_key("") == ""


def test_plate_media_puts_plate_in_current_slot(tmp_path: Path) -> None:
    from bpe.core.confirm_media import find_plate_media, shot_root_from_plate, usual_shot_root

    shot = tmp_path / "PRJ" / "04_sq" / "ep01" / "ep01_s010_0010"
    plate = shot / "plate" / "org" / "v002" / "mov" / "ep01_s010_0010_org.mov"
    plate.parent.mkdir(parents=True)
    plate.write_bytes(b"x")
    edit = shot / "edit" / "v001" / "ep01_s010_0010_edit.mov"
    edit.parent.mkdir(parents=True)
    edit.write_bytes(b"x")

    assert usual_shot_root(str(tmp_path), "PRJ", "ep01_s010_0010") == shot
    assert usual_shot_root(str(tmp_path), "PRJ", "ep01_s999_0010") is None
    assert usual_shot_root(str(tmp_path), "", "ep01_s010_0010") is None
    assert shot_root_from_plate(plate) == shot
    assert shot_root_from_plate(tmp_path / "somewhere" / "a.mov") is None

    media = find_plate_media(plate)
    assert media.shot_root == shot
    assert media.current is not None and media.current.path == plate
    assert media.current.version == 2 and not media.current.has_lut_baked  # 버전은 폴더 이름에서
    assert media.previous is None and media.org is None
    assert media.edit == edit


def test_reference_sources_lists_latest_work_first(tmp_path: Path) -> None:
    from bpe.core.confirm_media import reference_sources

    shot = tmp_path / "ep01_s010_0010"
    files = [
        shot / "comp" / "devl" / "renders" / "ep01_s010_0010_comp_v001.mov",
        shot / "comp" / "devl" / "renders" / "ep01_s010_0010_comp_v003.mov",
        shot / "plate" / "org" / "v001" / "mov" / "ep01_s010_0010_org.mov",
        shot / "edit" / "ep01_s010_0010_edit.mov",
    ]
    for f in files:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    got = reference_sources(shot)
    assert [name for name, _p in got] == ["comp v003", "ORG plate", "edit"]
    assert got[0][1] == files[1]
    assert reference_sources(tmp_path / "none") == []
