"""Tests for bpe.core.feedback_file_log."""

from __future__ import annotations

import json

from bpe.core.feedback_file_log import (
    append_feedback_log,
    append_feedback_log_verbose,
    feedback_log_dir,
    is_feedback_diag_verbose,
    reset_feedback_diag_verbose_cache,
)


def _clear_diag_env(monkeypatch) -> None:
    monkeypatch.delenv("BPE_FEEDBACK_DIAG_VERBOSE", raising=False)
    monkeypatch.delenv("BPE_FEEDBACK_DIAG_QUIET", raising=False)


def test_default_verbose_writes(tmp_path, monkeypatch) -> None:
    _clear_diag_env(monkeypatch)
    reset_feedback_diag_verbose_cache()
    assert is_feedback_diag_verbose() is True
    monkeypatch.setattr("bpe.core.feedback_file_log.feedback_log_dir", lambda: tmp_path)
    append_feedback_log_verbose("v_default", x=1)
    log = tmp_path / "bpe_feedback.log"
    assert log.is_file()
    line = json.loads(log.read_text(encoding="utf-8").strip())
    assert line["event"] == "v_default"


def test_quiet_env_suppresses_verbose(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BPE_FEEDBACK_DIAG_QUIET", "1")
    reset_feedback_diag_verbose_cache()
    assert is_feedback_diag_verbose() is False
    monkeypatch.setattr("bpe.core.feedback_file_log.feedback_log_dir", lambda: tmp_path)
    append_feedback_log_verbose("v_only", x=1)
    log = tmp_path / "bpe_feedback.log"
    assert not log.exists()


def test_verbose_explicit_zero_suppresses(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BPE_FEEDBACK_DIAG_VERBOSE", "0")
    reset_feedback_diag_verbose_cache()
    assert is_feedback_diag_verbose() is False
    monkeypatch.setattr("bpe.core.feedback_file_log.feedback_log_dir", lambda: tmp_path)
    append_feedback_log_verbose("v_only", x=1)
    assert not (tmp_path / "bpe_feedback.log").exists()


def test_feedback_log_dir_env_override(tmp_path, monkeypatch) -> None:
    sub = tmp_path / "logs_here"
    monkeypatch.setenv("BPE_FEEDBACK_LOG_DIR", str(sub))
    assert feedback_log_dir() == sub.resolve()


def test_append_always_writes(tmp_path, monkeypatch) -> None:
    _clear_diag_env(monkeypatch)
    reset_feedback_diag_verbose_cache()
    monkeypatch.setattr("bpe.core.feedback_file_log.feedback_log_dir", lambda: tmp_path)
    append_feedback_log("base_evt", z=3)
    log = tmp_path / "bpe_feedback.log"
    line = json.loads(log.read_text(encoding="utf-8").strip())
    assert line["event"] == "base_evt"
