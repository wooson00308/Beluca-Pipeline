"""Nuke 세팅 공유 폴더 — 미디어 라이브러리와 분리."""

from __future__ import annotations

from pathlib import Path

from bpe.core import nuke_setup_library as nsl


def test_register_and_list_setup(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    monkeypatch.setattr("bpe.core.nuke_setup_library.config_dir", lambda: tmp_path / "shared")
    file_name = nsl.unique_file_name("주필산 Write")
    assert file_name.endswith(".nk")
    nsl.write_nk_text(file_name, "BackdropNode {\n name BD1\n}\n")
    assert (tmp_path / "shared" / "nuke_setups" / file_name).is_file()
    entry = nsl.register_setup_file("주필산 Write", file_name)
    assert entry["name"] == "주필산 Write"
    items = nsl.list_setups()
    assert len(items) == 1
    assert items[0]["file"] == file_name
    assert nsl.find_setup(entry["id"]) is not None
    other = nsl.unique_file_name("주필산 Write")
    assert other != file_name


def test_safe_stem_and_display_path(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    monkeypatch.setattr("bpe.core.nuke_setup_library.config_dir", lambda: tmp_path / "shared")
    assert " " not in nsl.safe_stem("a b/c")
    nsl.write_nk_text("demo.nk", "x\n")
    shown = nsl.nk_path_display("demo.nk")
    assert "zeus" not in shown.lower()
    assert "demo.nk" in shown.replace("\\", "/")


def test_groups_and_card_info_no_author_date(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    monkeypatch.setattr("bpe.core.nuke_setup_library.config_dir", lambda: tmp_path / "shared")
    assert nsl.add_group("Write세팅")
    nsl.write_nk_text(
        "w.nk",
        "Write {\n name Write1\n}\nGrade {\n name Grade1\n}\nGrade {\n name Grade2\n}\n",
    )
    entry = nsl.register_setup_file("내 Write", "w.nk", group="Write세팅")
    assert entry["group"] == "Write세팅"
    assert entry.get("folder_path") == "Write세팅"
    assert nsl.list_groups() == ["Write세팅"]
    only = nsl.list_setups(group="Write세팅")
    assert len(only) == 1
    card = nsl.setup_card_info(only[0])
    assert card["name"] == "내 Write"
    assert "updated" not in card
    assert "by" not in card
    assert "Write" in card["nodes"]
    assert "Grade" in card["nodes"]
    assert nsl.set_setup_group(entry["id"], "")
    assert nsl.list_setups(group="")[0]["id"] == entry["id"]


def test_nested_folders_and_v2_migrate(tmp_path: Path, monkeypatch, tmp_app_dir: Path):
    monkeypatch.setattr("bpe.core.nuke_setup_library.config_dir", lambda: tmp_path / "shared")
    assert nsl.add_folder("Write세팅")
    assert nsl.add_folder_under("Write세팅", "QC")
    nsl.write_nk_text("a.nk", "Write {\n name W\n}\n")
    entry = nsl.register_setup_file("A", "a.nk", folder_path="Write세팅/QC")
    assert entry["folder_path"] == "Write세팅/QC"
    assert len(nsl.list_setups(folder_path="Write세팅/QC")) == 1
    assert nsl.list_setups(folder_path="Write세팅") == []
    assert len(nsl.list_setups_under("Write세팅")) == 1
    assert nsl.rename_folder_at("Write세팅/QC", "QC2")
    assert nsl.list_setups(folder_path="Write세팅/QC2")[0]["id"] == entry["id"]
    assert nsl.delete_folder_at("Write세팅/QC2")
    assert nsl.list_setups(folder_path="")[0]["id"] == entry["id"]
    # v2 flat index migrate
    from bpe.core.atomic_io import write_json_file

    write_json_file(
        nsl.index_path(),
        {
            "version": 2,
            "groups": ["Gizmo"],
            "items": [
                {
                    "id": "old",
                    "name": "Old",
                    "file": "a.nk",
                    "group": "Gizmo",
                    "updated_at": "",
                    "updated_by": "",
                }
            ],
        },
    )
    loaded = nsl.load_index()
    assert loaded["version"] == 3
    assert any(f.get("name") == "Gizmo" for f in loaded.get("folders") or [])
    assert nsl.list_setups(folder_path="Gizmo")[0]["id"] == "old"
