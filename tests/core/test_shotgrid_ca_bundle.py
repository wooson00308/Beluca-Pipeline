"""Tests for bpe.core.shotgrid_ca_bundle."""

from __future__ import annotations

from pathlib import Path

import pytest

from bpe.core.shotgrid_ca_bundle import resolve_shotgun_ca_certs_path


def test_no_extra_ca_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BPE_SHOTGRID_NO_EXTRA_CA", "1")
    assert resolve_shotgun_ca_certs_path({"ca_certs": "/nope/notfound.pem"}) is None


def test_explicit_path_wins(tmp_path: Path) -> None:
    pem = tmp_path / "a.pem"
    pem.write_text("x", encoding="utf-8")
    assert resolve_shotgun_ca_certs_path({"ca_certs": str(pem)}) == str(pem.resolve())


def test_missing_explicit_falls_back_to_bundled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "bpe_sg_merged.pem"
    fake.write_text("bundle", encoding="utf-8")

    import bpe.core.shotgrid_ca_bundle as mod

    monkeypatch.setattr(mod, "_bundled_merged_pem_path", lambda: fake)
    assert resolve_shotgun_ca_certs_path({"ca_certs": ""}) == str(fake.resolve())
