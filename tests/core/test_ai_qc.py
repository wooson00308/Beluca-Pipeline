# @cursor-change: 2026-05-14, 0.3.0, _parse_result·analyze_frames 반환 타입(Tuple) 테스트 추가
"""tests/core/test_ai_qc.py — ai_qc 모듈 단위 테스트."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

import pytest

from bpe.core.ai_qc import (
    AiQcIssue,
    AiQcSettings,
    _parse_issues,
    analyze_frames,
    build_system_prompt,
    get_api_key,
)

# ── _parse_issues ─────────────────────────────────────────────────────────────


class TestParseIssues:
    def test_valid_json_array(self) -> None:
        raw = '[{"frame": 1042, "severity": "HIGH", "note": "테스트 이슈"}]'
        issues = _parse_issues(raw)
        assert len(issues) == 1
        assert issues[0].frame == 1042
        assert issues[0].severity == "HIGH"
        assert issues[0].note == "테스트 이슈"

    def test_json_in_markdown_codeblock(self) -> None:
        raw = '```json\n[{"frame": 10, "severity": "MED", "note": "노트"}]\n```'
        issues = _parse_issues(raw)
        assert len(issues) == 1
        assert issues[0].severity == "MED"

    def test_empty_array(self) -> None:
        assert _parse_issues("[]") == []

    def test_unknown_severity_defaults_to_med(self) -> None:
        raw = '[{"frame": 5, "severity": "CRITICAL", "note": "뭔가"}]'
        issues = _parse_issues(raw)
        assert issues[0].severity == "MED"

    def test_missing_note_skipped(self) -> None:
        raw = '[{"frame": 5, "severity": "LOW", "note": ""}]'
        issues = _parse_issues(raw)
        assert len(issues) == 0

    def test_no_json_array_returns_empty(self) -> None:
        assert _parse_issues("이슈 없음") == []

    def test_malformed_json_returns_empty(self) -> None:
        assert _parse_issues('[{"frame": 1, "severity":}]') == []

    def test_multiple_issues(self) -> None:
        raw = json.dumps(
            [
                {"frame": 1, "severity": "HIGH", "note": "A"},
                {"frame": 2, "severity": "LOW", "note": "B"},
            ]
        )
        issues = _parse_issues(raw)
        assert len(issues) == 2
        assert issues[0].severity == "HIGH"
        assert issues[1].severity == "LOW"


# ── _parse_result (verdict + issues) ─────────────────────────────────────────


class TestParseResult:
    def test_json_object_confirm(self) -> None:
        from bpe.core.ai_qc import _parse_result

        raw = '{"verdict": "CONFIRM", "reason": "품질 양호.", "issues": []}'
        verdict, issues = _parse_result(raw)
        assert verdict == "CONFIRM"
        assert issues == []

    def test_json_object_retake_with_issues(self) -> None:
        from bpe.core.ai_qc import _parse_result

        raw = json.dumps(
            {
                "verdict": "RETAKE",
                "reason": "엣지 이슈.",
                "issues": [{"frame": 5, "severity": "HIGH", "note": "검은 띠"}],
            }
        )
        verdict, issues = _parse_result(raw)
        assert verdict == "RETAKE"
        assert len(issues) == 1
        assert issues[0].severity == "HIGH"

    def test_json_object_in_markdown_codeblock(self) -> None:
        from bpe.core.ai_qc import _parse_result

        raw = '```json\n{"verdict": "CONFIRM", "reason": "OK", "issues": []}\n```'
        verdict, issues = _parse_result(raw)
        assert verdict == "CONFIRM"

    def test_fallback_array_no_issues_gives_confirm(self) -> None:
        from bpe.core.ai_qc import _parse_result

        verdict, issues = _parse_result("[]")
        assert verdict == "CONFIRM"
        assert issues == []

    def test_fallback_array_with_high_gives_retake(self) -> None:
        from bpe.core.ai_qc import _parse_result

        raw = '[{"frame": 1, "severity": "HIGH", "note": "이슈"}]'
        verdict, issues = _parse_result(raw)
        assert verdict == "RETAKE"
        assert len(issues) == 1

    def test_invalid_verdict_defaults_to_retake(self) -> None:
        from bpe.core.ai_qc import _parse_result

        raw = '{"verdict": "MAYBE", "issues": []}'
        verdict, issues = _parse_result(raw)
        assert verdict == "RETAKE"

    def test_no_json_returns_retake_empty(self) -> None:
        from bpe.core.ai_qc import _parse_result

        verdict, issues = _parse_result("이슈 없음")
        assert verdict == "CONFIRM"
        assert issues == []


# ── Gemini 응답 파싱 헬퍼 ─────────────────────────────────────────────────────


class TestGeminiPayloadText:
    def test_concat_text_parts(self) -> None:
        from bpe.core.ai_qc import _gemini_payload_text

        payload: Dict[str, Any] = {
            "candidates": [
                {"content": {"parts": [{"text": "hello"}, {"text": "world"}]}},
                {"content": {"parts": [{"text": "!"}]}},
            ]
        }
        assert _gemini_payload_text(payload) == "helloworld!"


# ── analyze_frames provider 디스패치 (모킹) ───────────────────────────────────


class TestAnalyzeFramesDispatch:
    def test_google_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BPE_AI_QC_API_KEY", raising=False)
        from bpe.core import ai_qc

        called: List[str] = []

        def _fake_google(
            frames: Any,
            settings: AiQcSettings,
            api_key: str,
            system_prompt: str,
        ) -> Tuple[str, List[AiQcIssue]]:
            called.append(settings.provider)
            return "CONFIRM", []

        with patch.object(ai_qc, "_call_google", _fake_google):
            verdict, issues = analyze_frames([], AiQcSettings(provider="google", api_key="k"))
        assert called == ["google"]
        assert verdict == "CONFIRM"
        assert issues == []

    def test_unknown_provider_uses_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BPE_AI_QC_API_KEY", raising=False)
        from bpe.core import ai_qc

        called: List[str] = []

        def _fake_openai(
            frames: Any,
            settings: AiQcSettings,
            api_key: str,
            system_prompt: str,
        ) -> Tuple[str, List[AiQcIssue]]:
            called.append("openai")
            return "RETAKE", []

        with patch.object(ai_qc, "_call_openai", _fake_openai):
            verdict, issues = analyze_frames(
                [], AiQcSettings(provider="unknown-vendor", api_key="k")
            )
        assert called == ["openai"]
        assert verdict == "RETAKE"


# ── get_api_key ───────────────────────────────────────────────────────────────


class TestGetApiKey:
    def test_env_var_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BPE_AI_QC_API_KEY", "env-key-123")
        s = AiQcSettings(api_key="settings-key")
        assert get_api_key(s) == "env-key-123"

    def test_falls_back_to_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BPE_AI_QC_API_KEY", raising=False)
        s = AiQcSettings(api_key="settings-key")
        assert get_api_key(s) == "settings-key"

    def test_empty_when_nothing_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BPE_AI_QC_API_KEY", raising=False)
        assert get_api_key(AiQcSettings()) == ""


# ── build_system_prompt ───────────────────────────────────────────────────────


class TestBuildSystemPrompt:
    def test_base_prompt_no_context(self) -> None:
        prompt = build_system_prompt()
        assert "senior VFX" in prompt
        assert "CONFIRM" in prompt

    def test_bg_comp_step_injected(self) -> None:
        ctx: Dict[str, Any] = {"step_name": "BG COMP", "notes": []}
        prompt = build_system_prompt(ctx)
        assert "background compositing" in prompt.lower()

    def test_remove_step_injected(self) -> None:
        ctx: Dict[str, Any] = {"step_name": "REMOVE", "notes": []}
        prompt = build_system_prompt(ctx)
        assert "removal" in prompt.lower()

    def test_notes_injected(self) -> None:
        ctx: Dict[str, Any] = {
            "step_name": "KEY",
            "notes": [{"content": "머리카락 처리 주의", "created_ago": "3일 전"}],
        }
        prompt = build_system_prompt(ctx)
        assert "머리카락" in prompt
        assert "3일 전" in prompt

    def test_unknown_step_no_extra(self) -> None:
        ctx: Dict[str, Any] = {"step_name": "UNKNOWN_STEP_XYZ", "notes": []}
        prompt = build_system_prompt(ctx)
        assert "UNKNOWN_STEP_XYZ" not in prompt

    def test_plate_comparison_flag(self) -> None:
        prompt = build_system_prompt(with_plate_comparison=True)
        assert "LEFT = original plate" in prompt

    def test_notes_timestamp_fallback(self) -> None:
        ctx: Dict[str, Any] = {
            "notes": [{"content": "노트 본문", "timestamp": "2024-05-01"}],
        }
        prompt = build_system_prompt(ctx)
        assert "노트 본문" in prompt
        assert "2024-05-01" in prompt

    def test_manual_prompt_extra(self) -> None:
        ctx: Dict[str, Any] = {"manual_prompt_extra": "수동: 얼굴 영역 디테일"}
        prompt = build_system_prompt(ctx)
        assert "얼굴" in prompt
        assert "수동" in prompt


class TestAiQcSettings:
    def test_default_values(self) -> None:
        s = AiQcSettings()
        assert s.provider == "openai"
        assert s.sample_count == 20
        assert s.use_sg_context is True
        assert s.api_key == ""

    def test_custom_values(self) -> None:
        s = AiQcSettings(provider="anthropic", sample_count=30, api_key="test")
        assert s.provider == "anthropic"
        assert s.sample_count == 30
        assert s.api_key == "test"


# ── settings 저장/로드 ────────────────────────────────────────────────────────


class TestAiQcSettingsPersistence:
    def test_get_default_settings(self, tmp_path: Path) -> None:
        from bpe.core.settings import get_ai_qc_settings

        sf = tmp_path / "settings.json"
        result = get_ai_qc_settings(sf)
        assert result["provider"] == "openai"
        assert result["sample_count"] == 20
        assert result["use_sg_context"] is True

    def test_save_and_reload(self, tmp_path: Path) -> None:
        from bpe.core.settings import get_ai_qc_settings, save_ai_qc_settings

        sf = tmp_path / "settings.json"
        save_ai_qc_settings({"provider": "anthropic", "sample_count": 40}, sf)
        result = get_ai_qc_settings(sf)
        assert result["provider"] == "anthropic"
        assert result["sample_count"] == 40
        # 다른 키는 기본값 유지
        assert result["use_sg_context"] is True

    def test_preserves_other_settings_keys(self, tmp_path: Path) -> None:
        from bpe.core.atomic_io import write_json_file
        from bpe.core.settings import save_ai_qc_settings

        sf = tmp_path / "settings.json"
        write_json_file(sf, {"presets_dir": "/some/path", "feedback": {"frame_start": 1001}})
        save_ai_qc_settings({"provider": "openai"}, sf)
        from bpe.core.settings import load_settings

        data = load_settings(sf)
        assert data.get("presets_dir") == "/some/path"
        assert data.get("feedback") == {"frame_start": 1001}
        assert "ai_qc" in data

    def test_invalid_key_ignored(self, tmp_path: Path) -> None:
        from bpe.core.settings import get_ai_qc_settings, save_ai_qc_settings

        sf = tmp_path / "settings.json"
        save_ai_qc_settings({"unknown_key": "value"}, sf)
        result = get_ai_qc_settings(sf)
        assert "unknown_key" not in result


# ── compare_metadata (Phase 2) ───────────────────────────────────────────────


class TestCompareMetadata:
    def _make_ffprobe_response(
        self, fps: str = "24/1", width: int = 1920, height: int = 1080, nb_frames: str = "100"
    ) -> str:
        return json.dumps(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "r_frame_rate": fps,
                        "width": width,
                        "height": height,
                        "nb_frames": nb_frames,
                    }
                ],
                "format": {},
            }
        )

    def test_no_mismatches_when_equal(self, tmp_path: Path) -> None:
        from bpe.core.ai_qc import compare_metadata

        mock_result = MagicMock()
        mock_result.stdout = self._make_ffprobe_response().encode()

        with patch("subprocess.run", return_value=mock_result):
            mismatches = compare_metadata(
                str(tmp_path / "plate.mov"),
                str(tmp_path / "comp.mov"),
                ffprobe_bin="ffprobe",
            )
        assert mismatches == []

    def test_fps_mismatch_detected(self, tmp_path: Path) -> None:
        from bpe.core.ai_qc import compare_metadata

        plate_resp = self._make_ffprobe_response(fps="24/1").encode()
        comp_resp = self._make_ffprobe_response(fps="24000/1001").encode()

        call_count = 0

        def _mock_run(cmd: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.stdout = plate_resp if call_count == 1 else comp_resp
            return r

        with patch("subprocess.run", side_effect=_mock_run):
            mismatches = compare_metadata(
                str(tmp_path / "plate.mov"),
                str(tmp_path / "comp.mov"),
                ffprobe_bin="ffprobe",
            )
        fps_mm = [m for m in mismatches if m.field == "FPS"]
        assert len(fps_mm) == 1
        assert "24.000" in fps_mm[0].plate_val

    def test_resolution_mismatch_detected(self, tmp_path: Path) -> None:
        from bpe.core.ai_qc import compare_metadata

        plate_resp = self._make_ffprobe_response(width=1920, height=1080).encode()
        comp_resp = self._make_ffprobe_response(width=3840, height=2160).encode()
        call_count = 0

        def _mock_run(cmd: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.stdout = plate_resp if call_count == 1 else comp_resp
            return r

        with patch("subprocess.run", side_effect=_mock_run):
            mismatches = compare_metadata(
                str(tmp_path / "plate.mov"),
                str(tmp_path / "comp.mov"),
                ffprobe_bin="ffprobe",
            )
        res_mm = [m for m in mismatches if m.field == "해상도"]
        assert len(res_mm) == 1
        assert "1920x1080" in res_mm[0].plate_val
        assert "3840x2160" in res_mm[0].comp_val

    def test_frame_count_mismatch_detected(self, tmp_path: Path) -> None:
        from bpe.core.ai_qc import compare_metadata

        plate_resp = self._make_ffprobe_response(nb_frames="100").encode()
        comp_resp = self._make_ffprobe_response(nb_frames="80").encode()
        call_count = 0

        def _mock_run(cmd: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.stdout = plate_resp if call_count == 1 else comp_resp
            return r

        with patch("subprocess.run", side_effect=_mock_run):
            mismatches = compare_metadata(
                str(tmp_path / "plate.mov"),
                str(tmp_path / "comp.mov"),
                ffprobe_bin="ffprobe",
            )
        fc_mm = [m for m in mismatches if m.field == "프레임 수"]
        assert len(fc_mm) == 1

    def test_returns_empty_when_no_ffprobe(self, tmp_path: Path) -> None:
        from bpe.core.ai_qc import compare_metadata

        with patch("bpe.core.ai_qc.resolve_ffprobe", return_value=None):
            mismatches = compare_metadata(
                str(tmp_path / "plate.mov"),
                str(tmp_path / "comp.mov"),
            )
        assert mismatches == []


# ── extract_sample_frames 오류 처리 ──────────────────────────────────────────


class TestExtractSampleFrames:
    def test_raises_when_no_ffmpeg(self) -> None:
        from bpe.core.ai_qc import extract_sample_frames

        with patch("bpe.core.ai_qc.resolve_ffmpeg", return_value=None):
            with pytest.raises(RuntimeError, match="FFmpeg"):
                extract_sample_frames("/fake/path.mov", 5)

    def test_cancellation_returns_partial(self, tmp_path: Path) -> None:
        """cancelled_cb가 True를 반환하면 추출이 중단된다 (실제 ffmpeg 없이 모킹)."""
        from bpe.core.ai_qc import extract_sample_frames

        frame_file = tmp_path / "frame_0001.jpg"
        frame_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # minimal JPEG header

        def _mock_run(*args: Any, **kwargs: Any) -> MagicMock:
            # frame_%04d.jpg 파일 생성 시뮬레이션
            return MagicMock()

        cancelled = [True]  # 즉시 취소

        with (
            patch("bpe.core.ai_qc.resolve_ffmpeg", return_value="/usr/bin/ffmpeg"),
            patch("bpe.core.ai_qc._probe_video", return_value=(24.0, 100, 1920, 1080)),
            patch("subprocess.run", side_effect=_mock_run),
            patch(
                "pathlib.Path.glob",
                return_value=[frame_file],
            ),
        ):
            result = extract_sample_frames(
                "/fake/path.mov",
                5,
                cancelled_cb=lambda: cancelled[0],
            )
        assert result == []
