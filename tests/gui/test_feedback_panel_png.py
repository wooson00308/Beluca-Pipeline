"""Feedback 패널 PNG 리소스가 소스 트리에 존재하는지 확인."""

from __future__ import annotations

from pathlib import Path

from bpe.gui.feedback_panel_png import feedback_png_path, list_expected_feedback_png_stems


def test_feedback_png_files_exist_in_repo() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "bpe" / "gui" / "resources" / "feedback"
    for stem in list_expected_feedback_png_stems():
        p = root / f"{stem}.png"
        assert p.is_file(), f"missing {p}"


def test_feedback_png_path_resolves_when_file_present() -> None:
    p = feedback_png_path("feedback_text")
    assert p.is_file()
