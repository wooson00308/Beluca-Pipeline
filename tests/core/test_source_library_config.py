"""소스 라이브러리 공유 설정 — 루트↔그룹·CS 자동 생성(순서 이동 가능, 삭제 불가)."""

from __future__ import annotations

from pathlib import Path

from bpe.core import source_library_config as libcfg


def test_save_and_load_roundtrip(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    monkeypatch.setattr(libcfg, "config_dir", lambda: tmp_path / "shared")
    data = libcfg.empty_library()
    libcfg.set_scope(
        data,
        libcfg.COMMON_SCOPE,
        ["W:/lib/comp"],
        [{"name": libcfg.COMMON_LABEL, "folders": ["W:/lib/comp"]}],
    )
    libcfg.save_library(data)
    loaded = libcfg.load_library()
    assert loaded["common"]["roots"] == ["W:/lib/comp"]
    assert any(g["name"] == libcfg.COMMON_LABEL for g in loaded["common"]["groups"])
    assert loaded["common"]["groups"][0]["folders"] == ["W:/lib/comp"]


def test_probe_library_read_missing_file_is_none(tmp_path: Path):
    """파일이 아예 없음(최초 사용) — 실패로 취급하지 않는다."""
    assert libcfg.probe_library_read(tmp_path / "no_such" / "library.json") is None


def test_probe_library_read_valid_json_is_none(tmp_path: Path):
    p = tmp_path / "library.json"
    p.write_text('{"version": 5}', encoding="utf-8")
    assert libcfg.probe_library_read(p) is None


def test_probe_library_read_empty_file_is_none(tmp_path: Path):
    """빈 파일도 최초사용과 동일 취급 (atomic_io.read_json_file 과 정책 일치)."""
    p = tmp_path / "library.json"
    p.write_text("", encoding="utf-8")
    assert libcfg.probe_library_read(p) is None


def test_probe_library_read_corrupted_json_returns_reason(tmp_path: Path):
    p = tmp_path / "library.json"
    p.write_text("{not valid json", encoding="utf-8")
    reason = libcfg.probe_library_read(p)
    assert reason is not None
    assert "손상" in reason or "파싱" in reason


def test_roots_for_view_common_only():
    lib = libcfg.empty_library()
    libcfg.set_scope(lib, libcfg.COMMON_SCOPE, ["W:/common"], [])
    assert libcfg.roots_for_view(lib, None) == ["W:/common"]
    assert libcfg.roots_for_view(lib, "1") == ["W:/common"]


def test_load_fills_empty_groups_into_cs(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    monkeypatch.setattr(libcfg, "config_dir", lambda: tmp_path / "shared")
    data = {
        "version": 1,
        "common": {"roots": ["W:/library/element"], "groups": []},
        "projects": {},
    }
    libcfg.save_library(data)
    # save_library migrate without fill — write raw then load
    from bpe.core.atomic_io import write_json_file

    write_json_file(
        libcfg.config_path(),
        {"version": 1, "common": {"roots": ["W:/library/element"], "groups": []}, "projects": {}},
    )
    loaded = libcfg.load_library()
    assert loaded["common"]["groups"][0]["name"] == libcfg.COMMON_LABEL
    assert loaded["common"]["groups"][0]["folders"] == ["W:/library/element"]


def test_legacy_category_folders_absorbed_into_cs(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    monkeypatch.setattr(libcfg, "config_dir", lambda: tmp_path / "shared")
    from bpe.core.atomic_io import write_json_file

    write_json_file(
        libcfg.config_path(),
        {
            "version": 1,
            "common": {
                "roots": ["W:/library/element"],
                "groups": [
                    {
                        "name": "Fire",
                        "folders": ["W:/library/element/Fire"],
                    }
                ],
            },
            "projects": {},
        },
    )
    loaded = libcfg.load_library()
    # 레거시 카테고리 그룹은 사라지고 루트는 CS 로
    names = [g["name"] for g in loaded["common"]["groups"]]
    assert names == [libcfg.COMMON_LABEL]
    assert loaded["common"]["groups"][0]["folders"] == ["W:/library/element"]


def test_assign_roots_to_user_group():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/library/element", "W:/proj/mmk"],
        [{"name": libcfg.COMMON_LABEL, "folders": ["W:/library/element"]}],
    )
    n = libcfg.assign_roots_to_group(lib, ["W:/proj/mmk"], "mmk")
    assert n == 1
    groups = {g["name"]: g["folders"] for g in libcfg.view_groups(lib)}
    assert groups[libcfg.COMMON_LABEL] == ["W:/library/element"]
    assert groups["mmk"] == ["W:/proj/mmk"]
    assert libcfg.pack_roots(lib) == ["W:/library/element"]
    assert "W:/proj/mmk" not in libcfg.pack_roots(lib)
    assert libcfg.unassigned_roots(lib) == []


def test_refresh_root_choices_excludes_pack_roots():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/library/element", "W:\\proj\\clips\\", "W:/proj/data"],
        [{"name": libcfg.COMMON_LABEL, "folders": ["W:/library/element"]}],
    )
    choices = libcfg.refresh_root_choices(lib)
    assert choices == [
        ("W:/library/element", False),
        ("W:/proj/clips", True),
        ("W:/proj/data", True),
    ]


def test_refresh_root_choices_empty_library():
    assert libcfg.refresh_root_choices(libcfg.empty_library()) == []


def test_cannot_lose_builtin_group_on_view():
    lib = libcfg.empty_library()
    lib["common"] = {"roots": [], "groups": []}
    groups = libcfg.view_groups(lib)
    assert groups[0]["name"] == libcfg.COMMON_LABEL


def test_build_other_entries_skips_assigned_root_categories():
    scope = {
        "roots": ["W:/lib"],
        "groups": [{"name": libcfg.COMMON_LABEL, "folders": ["W:/lib"]}],
    }
    folders = [
        ("W:/lib", "Fire", 10),
        ("W:/lib", "Rain", 3),
    ]
    other = libcfg.build_other_entries(scope, folders)
    assert other == []


def test_category_pairs_for_group():
    group = {"name": "mmk", "folders": ["W:/proj/A"]}
    counts = [
        ("W:/proj/A", "onset", 5),
        ("W:/library/element", "Glass", 9),
    ]
    pairs = libcfg.category_pairs_for_group(group, counts)
    assert pairs == [("W:/proj/A", "onset", 5)]


def test_assign_roots_noop_when_path_not_registered():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/library/element"],
        [{"name": libcfg.COMMON_LABEL, "folders": ["W:/library/element"]}],
    )
    lib["common"]["groups"].append({"name": "mmk", "folders": [], "children": []})
    n = libcfg.assign_roots_to_group(lib, ["//zeus.lennon.co.kr/beluca/library/element"], "mmk")
    assert n == 0
    groups = {g["name"]: g["folders"] for g in libcfg.view_groups(lib)}
    assert groups.get("mmk") == []


def test_v2_children_roundtrip(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    monkeypatch.setattr(libcfg, "config_dir", lambda: tmp_path / "shared")
    data = libcfg.empty_library()
    libcfg.set_scope(
        data,
        libcfg.COMMON_SCOPE,
        ["W:/library/element"],
        [
            {
                "name": libcfg.COMMON_LABEL,
                "folders": ["W:/library/element"],
                "children": [
                    {
                        "name": "히어로샷",
                        "anchor": "W:/library/element/Explosions",
                        "folders": [],
                    }
                ],
            }
        ],
    )
    libcfg.save_library(data)
    loaded = libcfg.load_library()
    assert loaded["version"] == libcfg.CONFIG_VERSION
    children = loaded["common"]["groups"][0].get("children") or []
    assert len(children) == 1
    assert children[0]["name"] == "히어로샷"
    assert children[0]["anchor"] == "W:/library/element/Explosions"
    assert libcfg.pack_roots(loaded) == ["W:/library/element"]


def test_migrate_preserves_children():
    scope = {
        "roots": ["W:/library/element"],
        "groups": [
            {
                "name": libcfg.COMMON_LABEL,
                "folders": ["W:/library/element"],
                "children": [
                    {
                        "name": "A",
                        "anchor": "W:/library/element/Glass",
                        "folders": [],
                    }
                ],
            }
        ],
    }
    out = libcfg.migrate_groups_to_roots(scope, fill_empty_cs=False)
    assert out["groups"][0]["children"][0]["name"] == "A"
    assert out["groups"][0]["folders"] == ["W:/library/element"]


def test_add_nested_group():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/library/element"],
        [{"name": libcfg.COMMON_LABEL, "folders": ["W:/library/element"]}],
    )
    ok = libcfg.add_nested_group(
        lib, libcfg.COMMON_LABEL, "히어로", "W:/library/element/Explosions"
    )
    assert ok
    kids = libcfg.group_children(libcfg.view_groups(lib)[0])
    assert kids[0]["name"] == "히어로"


def test_nest_top_level_under_anchor_and_reparent():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/proj/mmk/04_의상소품사진"],
        [{"name": "MMK_028", "folders": ["W:/proj/mmk/04_의상소품사진"], "children": []}],
    )
    assert libcfg.add_top_level_group(lib, "주필산")
    assert libcfg.nest_group_under_anchor(lib, "주필산", "MMK_028", "W:/proj/mmk/04_의상소품사진")
    names = {g["name"] for g in libcfg.view_groups(lib)}
    assert "주필산" not in names
    g = next(g for g in libcfg.view_groups(lib) if g["name"] == "MMK_028")
    nested = libcfg.children_under_anchor(g, "W:/proj/mmk/04_의상소품사진")
    assert len(nested) == 1 and nested[0]["name"] == "주필산"
    assert libcfg.reparent_nested_group(
        lib, "MMK_028", "주필산", "W:/proj/mmk/04_의상소품사진/소품"
    )
    g2 = next(x for x in libcfg.view_groups(lib) if x["name"] == "MMK_028")
    assert libcfg.children_under_anchor(g2, "W:/proj/mmk/04_의상소품사진") == []
    assert libcfg.children_under_anchor(g2, "W:/proj/mmk/04_의상소품사진/소품")[0]["name"] == (
        "주필산"
    )
    assert libcfg.unnest_to_top_level(lib, "MMK_028", "주필산")
    assert "주필산" in {x["name"] for x in libcfg.view_groups(lib)}


def test_organized_paths_hides_siblings():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/proj/mmk"],
        [{"name": "MMK_028", "folders": ["W:/proj/mmk"], "children": []}],
    )
    assert libcfg.add_virtual_folder(lib, "MMK_028", "주필산")
    assert libcfg.assign_category_to_virtual(lib, "MMK_028", "주필산", "W:/proj/mmk/AI_소품")
    g = next(x for x in libcfg.view_groups(lib) if x["name"] == "MMK_028")
    org = libcfg.organized_paths(g)
    assert "W:/proj/mmk/AI_소품" in org
    assert "W:/proj/mmk/소품" not in org
    assert libcfg.remove_category_from_virtual(lib, "MMK_028", "주필산", "W:/proj/mmk/AI_소품")
    g2 = next(x for x in libcfg.view_groups(lib) if x["name"] == "MMK_028")
    assert "W:/proj/mmk/AI_소품" not in libcfg.organized_paths(g2)


def test_add_top_level_and_move_virtual():
    lib = libcfg.empty_library()
    libcfg.set_scope(lib, libcfg.COMMON_SCOPE, ["W:/proj/mmk"], [])
    assert libcfg.add_top_level_group(lib, "MMK_28")
    assert not libcfg.add_top_level_group(lib, "MMK_28")
    assert libcfg.add_virtual_folder(lib, "MMK_28", "주필산")
    assert libcfg.add_top_level_group(lib, "프로젝트")
    assert libcfg.move_virtual_folder(lib, "MMK_28", "주필산", "프로젝트")
    g_proj = next(g for g in libcfg.view_groups(lib) if g["name"] == "프로젝트")
    assert [c["name"] for c in libcfg.virtual_children(g_proj)] == ["주필산"]
    g_mmk = next(g for g in libcfg.view_groups(lib) if g["name"] == "MMK_28")
    assert libcfg.virtual_children(g_mmk) == []


def test_virtual_folder_assign_and_keys():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/proj/mmk"],
        [{"name": "MMK_28", "folders": ["W:/proj/mmk"], "children": []}],
    )
    assert libcfg.add_virtual_folder(lib, "MMK_28", "주필산")
    assert libcfg.assign_category_to_virtual(lib, "MMK_28", "주필산", "W:/proj/mmk/Fire")
    g = next(g for g in libcfg.view_groups(lib) if g["name"] == "MMK_28")
    vc = libcfg.virtual_children(g)[0]
    assert vc["kind"] == libcfg.CHILD_KIND_VIRTUAL
    assert vc["folders"] == ["W:/proj/mmk/Fire"]
    keys = libcfg.folder_keys_for_virtual_child(vc, ["W:/proj/mmk"])
    assert keys == [("W:/proj/mmk", "Fire")]
    assert libcfg.remove_category_from_virtual(lib, "MMK_28", "주필산", "W:/proj/mmk/Fire")
    g2 = next(g for g in libcfg.view_groups(lib) if g["name"] == "MMK_28")
    assert libcfg.virtual_children(g2)[0]["folders"] == []
    # 중첩(anchor)만 children_under_anchor 에 남음
    assert libcfg.children_under_anchor(g2, "W:/proj/mmk/Fire") == []


def test_virtual_folder_assign_preserves_deep_dir_rel():
    """서버가 2단계 이상 깊어도 folder_keys_for_virtual_child 가 전체 상대경로를 보존한다."""
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/proj/mmk"],
        [{"name": "MMK_28", "folders": ["W:/proj/mmk"], "children": []}],
    )
    assert libcfg.add_virtual_folder(lib, "MMK_28", "현장데이터")
    assert libcfg.assign_category_to_virtual(
        lib, "MMK_28", "현장데이터", "W:/proj/mmk/260125_3회차/insta360"
    )
    g = next(g for g in libcfg.view_groups(lib) if g["name"] == "MMK_28")
    vc = libcfg.virtual_children(g)[0]
    keys = libcfg.folder_keys_for_virtual_child(vc, ["W:/proj/mmk"])
    # 1단계로 뭉개지지 않고 "260125_3회차/insta360" 전체가 dir_rel 로 남아야 한다.
    assert keys == [("W:/proj/mmk", "260125_3회차/insta360")]


def test_list_disk_subdirs(tmp_path: Path):
    (tmp_path / "Glass").mkdir()
    (tmp_path / "Explosions").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    names = libcfg.list_disk_subdirs(str(tmp_path))
    assert names == ["Explosions", "Glass"]


def test_has_disk_subdir(tmp_path: Path):
    leaf = tmp_path / "leaf"
    leaf.mkdir()
    parent = tmp_path
    assert libcfg.has_disk_subdir(str(parent)) is True
    assert libcfg.has_disk_subdir(str(leaf)) is False
    (leaf / "deeper").mkdir()
    assert libcfg.has_disk_subdir(str(leaf)) is True
    assert libcfg.has_disk_subdir(str(tmp_path / "missing")) is False


def test_does_not_touch_media_files(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    media = tmp_path / "media"
    media.mkdir()
    sample = media / "a.exr"
    sample.write_bytes(b"x")
    before = list(media.iterdir())
    monkeypatch.setattr(libcfg, "config_dir", lambda: tmp_path / "shared")
    data = libcfg.empty_library()
    libcfg.set_scope(
        data,
        libcfg.COMMON_SCOPE,
        [str(media).replace("\\", "/")],
        [{"name": libcfg.COMMON_LABEL, "folders": [str(media).replace("\\", "/")]}],
    )
    libcfg.save_library(data)
    assert list(media.iterdir()) == before
    assert sample.read_bytes() == b"x"


def test_hidden_folders_persist_and_survive_set_scope(
    tmp_path: Path, monkeypatch, tmp_app_dir: Path
):
    monkeypatch.setattr(libcfg, "config_dir", lambda: tmp_path / "shared")
    data = libcfg.empty_library()
    libcfg.set_scope(
        data,
        libcfg.COMMON_SCOPE,
        ["W:/library/element"],
        [{"name": libcfg.COMMON_LABEL, "folders": ["W:/library/element"]}],
    )
    assert libcfg.set_folder_hidden(data, "W:/library/element/Fire", True)
    libcfg.save_library(data)
    loaded = libcfg.load_library()
    assert "W:/library/element/Fire" in libcfg.hidden_folders(loaded)
    assert libcfg.is_hidden_folder(loaded, "W:/library/element/Fire")
    assert libcfg.is_hidden_folder(loaded, "W:/library/element/Fire/sub")
    # set_scope 가 hidden 을 지우면 안 됨
    libcfg.set_scope(
        loaded,
        libcfg.COMMON_SCOPE,
        ["W:/library/element"],
        [{"name": libcfg.COMMON_LABEL, "folders": ["W:/library/element"]}],
    )
    assert "W:/library/element/Fire" in libcfg.hidden_folders(loaded)
    assert libcfg.set_folder_hidden(loaded, "W:/library/element/Fire", False)
    assert not libcfg.is_hidden_folder(loaded, "W:/library/element/Fire")


def test_recursive_virtual_children_roundtrip(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    monkeypatch.setattr(libcfg, "config_dir", lambda: tmp_path / "shared")
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/proj/mmk"],
        [{"name": "MMK_028", "folders": ["W:/proj/mmk"], "children": []}],
    )
    assert libcfg.add_folder_under(lib, "MMK_028", "주필산")
    assert libcfg.add_folder_under(lib, "MMK_028/주필산", "세부")
    assert libcfg.move_source_into_folder(lib, "MMK_028/주필산/세부", "W:/proj/mmk/AI_소품")
    libcfg.save_library(lib)
    loaded = libcfg.load_library()
    g = next(x for x in libcfg.view_groups(loaded) if x["name"] == "MMK_028")
    top = libcfg.virtual_children(g)[0]
    assert top["name"] == "주필산"
    nested = libcfg.virtual_children(top)[0]
    assert nested["name"] == "세부"
    assert nested["folders"] == ["W:/proj/mmk/AI_소품"]
    assert "W:/proj/mmk/AI_소품" in libcfg.organized_paths(g)


def test_move_folder_unnest_onto_ancestor_virtual():
    """하위 폴더를 조상 virtual로 빼면 직속으로 올라온다 (GUI 가드와 동일 규칙)."""
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/proj/mmk"],
        [{"name": "MMK_028", "folders": ["W:/proj/mmk"], "children": []}],
    )
    assert libcfg.add_folder_under(lib, "MMK_028", "주필산")
    assert libcfg.add_folder_under(lib, "MMK_028/주필산", "세부")
    assert libcfg.move_source_into_folder(lib, "MMK_028/주필산/세부", "W:/proj/mmk/AI_소품")
    # 자손으로는 불가
    assert not libcfg.move_folder(lib, "MMK_028/주필산", "MMK_028/주필산/세부")
    # 조상 virtual로 빼기 OK
    assert libcfg.move_folder(lib, "MMK_028/주필산/세부", "MMK_028")
    g = next(x for x in libcfg.view_groups(lib) if x["name"] == "MMK_028")
    names = [c["name"] for c in libcfg.virtual_children(g)]
    assert "세부" in names
    assert "주필산" in names
    leaf = next(c for c in libcfg.virtual_children(g) if c["name"] == "세부")
    assert leaf["folders"] == ["W:/proj/mmk/AI_소품"]


def test_top_level_org_folder_bag_and_roots_stable():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/proj/mmk"],
        [{"name": "MMK_028", "folders": ["W:/proj/mmk"], "children": []}],
    )
    assert libcfg.add_top_level_folder(lib, "주필산")
    g_folder = next(x for x in libcfg.view_groups(lib) if x["name"] == "주필산")
    assert libcfg.is_org_folder(g_folder)
    assert libcfg.move_source_into_folder(lib, "주필산", "W:/proj/mmk/AI_소품")
    g_folder = next(x for x in libcfg.view_groups(lib) if x["name"] == "주필산")
    assert g_folder.get("bag") == ["W:/proj/mmk/AI_소품"]
    g_mmk = next(x for x in libcfg.view_groups(lib) if x["name"] == "MMK_028")
    assert g_mmk.get("folders") == ["W:/proj/mmk"]
    assert "W:/proj/mmk/AI_소품" in libcfg.library_organized_paths(lib)
    assert libcfg.move_folder  # sanity
    assert libcfg.add_folder_under(lib, "주필산", "세부")
    assert libcfg.move_source_into_folder(lib, "주필산/세부", "W:/proj/mmk/AI_소품")
    g_folder = next(x for x in libcfg.view_groups(lib) if x["name"] == "주필산")
    assert g_folder.get("bag") == []
    assert libcfg.virtual_children(g_folder)[0]["folders"] == ["W:/proj/mmk/AI_소품"]
    assert libcfg.remove_source_from_folder(lib, "주필산/세부", "W:/proj/mmk/AI_소품")
    g_mmk2 = next(x for x in libcfg.view_groups(lib) if x["name"] == "MMK_028")
    assert g_mmk2.get("folders") == ["W:/proj/mmk"]


def test_assign_roots_rejected_for_org_folder():
    lib = libcfg.empty_library()
    libcfg.set_scope(lib, libcfg.COMMON_SCOPE, ["W:/proj/mmk"], [])
    assert libcfg.add_top_level_folder(lib, "주필산")
    assert libcfg.assign_roots_to_group(lib, ["W:/proj/mmk"], "주필산") == 0
    g = next(x for x in libcfg.view_groups(lib) if x["name"] == "주필산")
    assert g.get("folders") == []


def test_cs_bag_and_organize_into_folder():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/library/element"],
        [{"name": libcfg.COMMON_LABEL, "folders": ["W:/library/element"], "children": []}],
    )
    # CS 최상위 bag 직접 수납
    assert libcfg.move_source_into_folder(lib, libcfg.COMMON_LABEL, "W:/library/element/Fire")
    g = next(x for x in libcfg.view_groups(lib) if x["name"] == libcfg.COMMON_LABEL)
    assert "W:/library/element/Fire" in (g.get("bag") or [])
    # organize → 동명 virtual (평탄 dump 아님)
    assert libcfg.organize_into_folder(lib, libcfg.COMMON_LABEL, "W:/library/element/Water_Bubble")
    g = next(x for x in libcfg.view_groups(lib) if x["name"] == libcfg.COMMON_LABEL)
    names = [c["name"] for c in libcfg.virtual_children(g)]
    assert "Water_Bubble" in names
    vb = next(c for c in libcfg.virtual_children(g) if c["name"] == "Water_Bubble")
    assert vb.get("folders") == ["W:/library/element/Water_Bubble"]
    assert "W:/library/element/Water_Bubble" in libcfg.organized_paths(g)
    # 커스텀 폴더 아래 정리
    assert libcfg.add_folder_under(lib, libcfg.COMMON_LABEL, "물소스")
    assert libcfg.organize_into_folder(
        lib, "{}/물소스".format(libcfg.COMMON_LABEL), "W:/library/element/Water_Rain"
    )
    g = next(x for x in libcfg.view_groups(lib) if x["name"] == libcfg.COMMON_LABEL)
    water = next(c for c in libcfg.virtual_children(g) if c["name"] == "물소스")
    rain = next(c for c in libcfg.virtual_children(water) if c["name"] == "Water_Rain")
    assert rain.get("folders") == ["W:/library/element/Water_Rain"]


def test_migrate_bag_to_virtual_folders():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/proj/mmk"],
        [
            {
                "name": "MMK",
                "folders": ["W:/proj/mmk"],
                "children": [],
                "bag": ["W:/proj/mmk/260124_A", "W:/proj/mmk/260125_B"],
            }
        ],
    )
    n = libcfg.migrate_bag_to_virtual_folders(lib)
    assert n == 2
    g = next(x for x in libcfg.view_groups(lib) if x["name"] == "MMK")
    assert not (g.get("bag") or [])
    names = sorted(c["name"] for c in libcfg.virtual_children(g))
    assert names == ["260124_A", "260125_B"]


def test_reorder_folder_sibling():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/lib"],
        [{"name": libcfg.COMMON_LABEL, "folders": ["W:/lib"], "children": []}],
    )
    assert libcfg.add_folder_under(lib, libcfg.COMMON_LABEL, "A")
    assert libcfg.add_folder_under(lib, libcfg.COMMON_LABEL, "B")
    assert libcfg.add_folder_under(lib, libcfg.COMMON_LABEL, "C")
    assert libcfg.reorder_folder_sibling(
        lib,
        "{}/C".format(libcfg.COMMON_LABEL),
        "{}/A".format(libcfg.COMMON_LABEL),
        after=False,
    )
    g = next(x for x in libcfg.view_groups(lib) if x["name"] == libcfg.COMMON_LABEL)
    names = [c["name"] for c in libcfg.virtual_children(g)]
    assert names[0] == "C"
    assert "A" in names and "B" in names


def test_reorder_top_level_group(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    monkeypatch.setattr(libcfg, "config_dir", lambda: tmp_path / "shared")
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/lib"],
        [
            {"name": libcfg.COMMON_LABEL, "folders": ["W:/lib"], "children": []},
            {"name": "A", "folders": [], "children": []},
            {"name": "B", "folders": [], "children": []},
            {"name": "C", "folders": [], "children": []},
        ],
    )
    assert libcfg.reorder_top_level_group(lib, "C", "A", after=False)
    names = [g["name"] for g in libcfg.view_groups(lib)]
    assert names == [libcfg.COMMON_LABEL, "C", "A", "B"]

    assert libcfg.reorder_top_level_group(lib, "C", "A", after=True)
    names = [g["name"] for g in libcfg.view_groups(lib)]
    assert names == [libcfg.COMMON_LABEL, "A", "C", "B"]

    # CS(builtin)도 순서 이동 가능 (삭제·이름변경만 불가) — 이동 후 위치가 유지된다
    assert libcfg.reorder_top_level_group(lib, libcfg.COMMON_LABEL, "C", after=True)
    names = [g["name"] for g in libcfg.view_groups(lib)]
    assert names == ["A", "C", libcfg.COMMON_LABEL, "B"]

    # 저장·로드 왕복 후에도 CS 위치가 되돌아가지 않는다
    libcfg.save_library(lib)
    lib2 = libcfg.load_library()
    names2 = [g["name"] for g in libcfg.view_groups(lib2)]
    assert names2 == ["A", "C", libcfg.COMMON_LABEL, "B"]

    # 그룹이 2개뿐이어도(CS+1) 상호 교환 가능
    lib3 = libcfg.empty_library()
    libcfg.set_scope(
        lib3,
        libcfg.COMMON_SCOPE,
        ["W:/lib"],
        [
            {"name": libcfg.COMMON_LABEL, "folders": ["W:/lib"], "children": []},
            {"name": "MMK", "folders": [], "children": []},
        ],
    )
    assert libcfg.reorder_top_level_group(lib3, "MMK", libcfg.COMMON_LABEL, after=False)
    assert [g["name"] for g in libcfg.view_groups(lib3)] == ["MMK", libcfg.COMMON_LABEL]


def test_promote_preserves_bag_and_children():
    lib = libcfg.empty_library()
    libcfg.set_scope(
        lib,
        libcfg.COMMON_SCOPE,
        ["W:/proj/mmk"],
        [{"name": "MMK", "folders": ["W:/proj/mmk"], "children": []}],
    )
    assert libcfg.add_top_level_folder(lib, "주필산")
    assert libcfg.move_source_into_folder(lib, "주필산", "W:/proj/mmk/AI_소품")
    assert libcfg.add_folder_under(lib, "주필산", "세부")
    assert libcfg.promote_top_level_to_virtual(lib, "주필산", "MMK")
    g = next(x for x in libcfg.view_groups(lib) if x["name"] == "MMK")
    top = next(c for c in libcfg.virtual_children(g) if c["name"] == "주필산")
    assert "W:/proj/mmk/AI_소품" in (top.get("folders") or [])
    assert any(c.get("name") == "세부" for c in libcfg.virtual_children(top))
