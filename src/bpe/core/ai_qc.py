# @cursor-change: 2026-05-14, 0.3.0, AI QC — director급 프롬프트 + CONFIRM/RETAKE 판정 기능
"""AI QC — VFX comp 품질 분석 (OpenAI / Anthropic / Google Gemini / xAI / Mistral vision API).

코어 로직만. GUI·ShotGrid import 없음.
표준 라이브러리(urllib.request, json, base64, subprocess, tempfile) + Pillow(기존 의존성)만 사용.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bpe.core.ffmpeg_paths import resolve_ffmpeg, resolve_ffprobe
from bpe.core.logging import get_logger
from bpe.core.win_subprocess import no_console_subprocess_kwargs

logger = get_logger("core.ai_qc")

_MAX_EDGE = 1280
_JPEG_QUALITY = 88

# ── 파이프라인 스텝 → AI 포커스 프롬프트 ────────────────────────────────────
STEP_PROMPT_MAP: Dict[str, str] = {
    "BG COMP": (
        "This is a background compositing shot. "
        "Priority checks: (1) Color temperature and luminance match between plate background "
        "and composited foreground elements — mismatches appear as 'floating' subjects. "
        "(2) Edge integration — look for dark fringing, blue/green spill, halo artifacts "
        "around foreground against background. "
        "(3) Light direction consistency — rim light and shadow must match background "
        "light source. (4) Atmospheric depth — foreground should show matching "
        "fog/haze if background has depth cues. "
        "(5) Color continuity with adjacent cuts (앞컷/뒷컷 연결 확인)."
    ),
    "REMOVE": (
        "This is an object/person removal shot. "
        "Priority checks: (1) Background reconstruction quality — look for smearing, "
        "repeating texture patterns, or visible 'patch' edges in the removed area. "
        "(2) Grain consistency — reconstructed area grain must match surrounding plate. "
        "(3) Motion in background — if background has movement, verify reconstruction "
        "tracks correctly across frames (no ghosting or temporal instability). "
        "(4) Lighting continuity — no sudden brightness changes in the filled area."
    ),
    "KEY": (
        "This is a keying shot (green/blue screen). "
        "Priority checks: (1) Matte edge quality — fine hair/fabric detail retention, "
        "no missing thin elements. (2) Edge color — no green/blue spill contamination, "
        "no dark fringing ('검은 띠'), no color banding. "
        "(3) Semi-transparent areas — glass, smoke, motion-blurred edges must retain "
        "correct transparency and color. (4) Despill effectiveness — any residual "
        "screen color on subject skin/clothing. "
        "(5) Motion blur on edges — fast-moving elements need matching blur."
    ),
    "ROTO": (
        "This is a roto (rotoscope) shot. "
        "Priority checks: (1) Shape accuracy — matte edge must follow subject precisely "
        "with no cutting into subject or leaving background inside matte. "
        "(2) Temporal stability — no edge jitter or 'crawling' artifacts between frames. "
        "(3) Motion blur — fast-moving limbs need soft roto edges matching motion. "
        "(4) Fine detail — hair, fingers, loose clothing must be captured accurately."
    ),
    "DMP": (
        "This is a DMP (digital matte painting) shot. "
        "Priority checks: (1) Perspective consistency — painted elements must match "
        "camera perspective and any camera movement. "
        "(2) Lighting integration — DMP light direction, color temperature, and shadow "
        "angles must match the live-action plate. "
        "(3) Edge matching — seam between painted and live-action elements must be "
        "invisible. (4) Scale and proportion — DMP elements must feel realistic in scale."
    ),
}

_BASE_SYSTEM_PROMPT = (
    "You are a senior VFX Compositing Supervisor with 15+ years experience at "
    "Hollywood-level VFX facilities. Your job is to review these composite frames "
    "and give a studio-quality QC verdict — the same standard as a comp supervisor "
    "reviewing shots before client delivery.\n\n"
    "Examine every frame for the following issues:\n"
    "1. EDGE QUALITY — dark fringing ('검은 띠'), color spill on edges, key remnants, "
    "halo artifacts, missing fine hair/fabric detail\n"
    "2. LIGHT INTERACTION — light source direction vs subject response, rim light "
    "plausibility, floor/surface light bounce, eye catchlight, secondary spill on "
    "environment ('빛반응')\n"
    "3. COLOR & LUMINANCE — foreground vs background color temperature and brightness "
    "match, saturation consistency, cut-to-cut color continuity ('연결 컬러')\n"
    "4. FOCUS DEPTH — focus distance matching between plate and composite, "
    "foreground/background bokeh consistency ('포커스 거리 맞게')\n"
    "5. MOTION BLUR — blur amount proportional to subject speed and direction\n"
    "6. TRACKING & POSITION — composited element spatial stability, tracking accuracy\n"
    "7. ATMOSPHERE & DEPTH — fog/haze/aerial perspective integration ('포그감')\n"
    "8. GRAIN & TEXTURE — noise pattern match between plate and composited element\n"
    "9. RENDER ARTIFACTS — shadow/reflection plausibility, CG render errors\n\n"
    "CONFIRM CRITERIA (all must be met):\n"
    "- Zero HIGH severity issues\n"
    "- Edges show no visible fringing or color contamination\n"
    "- Light interaction is plausible and direction-consistent\n"
    "- Color/luminance well integrated with plate\n\n"
    "For each issue: state frame number, severity (HIGH/MED/LOW), and a concise "
    "actionable note in Korean.\n\n"
    "IMPORTANT: Respond with ONLY a valid JSON object in this exact format:\n"
    '{"verdict": "CONFIRM", "reason": "전반적으로 합성 품질 기준 충족.", "issues": []}\n'
    'or: {"verdict": "RETAKE", "reason": "엣지 및 빛반응 수정 필요.", '
    '"issues": [{"frame": 1042, "severity": "HIGH", "note": "엣지에 검은 띠."}]}\n'
    "Use verdict RETAKE if any HIGH severity issue exists or quality is not "
    "delivery-ready. Use CONFIRM if the shot meets broadcast/delivery standards."
)


# ── 데이터 클래스 ─────────────────────────────────────────────────────────────


@dataclass
class AiQcIssue:
    frame: int
    severity: str  # "HIGH" | "MED" | "LOW"
    note: str
    thumb_bytes: Optional[bytes] = field(default=None, compare=False)


@dataclass
class MetadataMismatch:
    field: str
    plate_val: str
    comp_val: str


@dataclass
class AiQcSettings:
    provider: str = "openai"
    api_key: str = ""
    sample_count: int = 20
    model: str = ""
    use_sg_context: bool = True
    sg_notes_limit: int = 3
    last_plate_path: str = ""


# ── API 키 ────────────────────────────────────────────────────────────────────


def get_api_key(settings: AiQcSettings) -> str:
    """BPE_AI_QC_API_KEY 환경변수 우선, 없으면 settings.api_key."""
    env = os.environ.get("BPE_AI_QC_API_KEY", "").strip()
    return env or (settings.api_key or "").strip()


# ── 이미지 리사이즈 ───────────────────────────────────────────────────────────


def _resize_jpeg(data: bytes, max_edge: int = _MAX_EDGE, quality: int = _JPEG_QUALITY) -> bytes:
    """Pillow로 JPEG를 max_edge 이하로 리사이즈. 실패 시 원본 반환."""
    try:
        from PIL import Image  # Pillow: 프로젝트 기존 의존성

        img = Image.open(BytesIO(data))
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_edge:
            ratio = max_edge / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception as exc:
        logger.debug("_resize_jpeg 실패: %s", exc)
        return data


# ── 비디오 프로빙 ─────────────────────────────────────────────────────────────


def _probe_video(path: str, ffprobe: Optional[str]) -> Tuple[float, int, int, int]:
    """(fps, total_frames, width, height) 반환. ffprobe 없으면 기본값."""
    if not ffprobe:
        return 24.0, 0, 0, 0
    cmd = [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", path]
    kw = no_console_subprocess_kwargs()
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30, check=True, **kw)
        data = json.loads(r.stdout)
        for s in data.get("streams") or []:
            if s.get("codec_type") != "video":
                continue
            fps = 24.0
            for key in ("r_frame_rate", "avg_frame_rate"):
                v = s.get(key, "")
                if v and "/" in v:
                    parts = v.split("/")
                    try:
                        val = float(parts[0]) / float(parts[1])
                        if val > 0:
                            fps = val
                            break
                    except (ValueError, ZeroDivisionError):
                        pass
            frames = int(s.get("nb_frames") or 0)
            w = int(s.get("width") or 0)
            h = int(s.get("height") or 0)
            if frames <= 0:
                dur = float(s.get("duration") or 0)
                if dur > 0 and fps > 0:
                    frames = int(round(dur * fps))
            return fps, frames, w, h
    except Exception as exc:
        logger.debug("_probe_video 실패 (%s): %s", path, exc)
    return 24.0, 0, 0, 0


# ── 프레임 추출 ───────────────────────────────────────────────────────────────


def extract_sample_frames(
    mov_path: str,
    count: int,
    *,
    ffmpeg_bin: Optional[str] = None,
    ffprobe_bin: Optional[str] = None,
    cancelled_cb: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[Tuple[int, bytes]]:
    """MOV에서 count개 프레임을 시간 균등하게 추출. [(0-based_frame_idx, jpeg_bytes), ...]."""
    ffmpeg = ffmpeg_bin or resolve_ffmpeg()
    ffprobe = ffprobe_bin or resolve_ffprobe()
    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg를 찾을 수 없습니다. FFMPEG_PATH 환경변수 또는 BPE_FFMPEG_BIN을 설정하세요."
        )
    count = max(1, int(count))

    fps, total_frames, _w, _h = _probe_video(mov_path, ffprobe)
    duration = total_frames / fps if fps > 0 and total_frames > 0 else 0.0

    with tempfile.TemporaryDirectory(prefix="bpe_aiqc_") as tmpdir:
        out_pattern = str(Path(tmpdir) / "frame_%04d.jpg")

        if duration > 0:
            sample_fps = count / duration
            cmd = [
                ffmpeg,
                "-y",
                "-i",
                mov_path,
                "-vf",
                f"fps={sample_fps:.6f}",
                "-frames:v",
                str(count),
                "-q:v",
                "3",
                out_pattern,
            ]
        else:
            interval = max(1, (total_frames or count) // count)
            cmd = [
                ffmpeg,
                "-y",
                "-i",
                mov_path,
                "-vf",
                f"select=not(mod(n\\,{interval}))",
                "-vsync",
                "0",
                "-frames:v",
                str(count),
                "-q:v",
                "3",
                out_pattern,
            ]

        kw = no_console_subprocess_kwargs()
        try:
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
                check=True,
                **kw,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"FFmpeg 프레임 추출 실패 (exitcode={exc.returncode})") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("FFmpeg 프레임 추출 시간 초과 (120초)") from exc

        frame_files = sorted(Path(tmpdir).glob("frame_*.jpg"))
        results: List[Tuple[int, bytes]] = []
        total = len(frame_files)
        for i, fp in enumerate(frame_files):
            if cancelled_cb and cancelled_cb():
                break
            if progress_cb:
                progress_cb(i / max(total, 1) * 0.5, f"프레임 추출 중... ({i + 1}/{total})")
            raw = fp.read_bytes()
            results.append((i, _resize_jpeg(raw)))

        return results


def extract_paired_frames(
    plate_path: str,
    comp_path: str,
    count: int,
    *,
    ffmpeg_bin: Optional[str] = None,
    cancelled_cb: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> List[Tuple[int, bytes, bytes]]:
    """Plate와 Comp에서 동일 타임코드 프레임 쌍 추출. [(frame_idx, plate_jpeg, comp_jpeg), ...]."""
    ffmpeg = ffmpeg_bin or resolve_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg를 찾을 수 없습니다.")

    count = max(1, int(count))
    ffprobe = resolve_ffprobe()
    fps, total_frames, _w, _h = _probe_video(comp_path, ffprobe)
    duration = total_frames / fps if fps > 0 and total_frames > 0 else 0.0

    with tempfile.TemporaryDirectory(prefix="bpe_aiqc_pair_") as tmpdir:
        tmpdir_p = Path(tmpdir)

        def _extract(src: str, prefix: str) -> List[Path]:
            out = str(tmpdir_p / f"{prefix}_%04d.jpg")
            if duration > 0:
                sample_fps = count / duration
                cmd = [
                    ffmpeg,
                    "-y",
                    "-i",
                    src,
                    "-vf",
                    f"fps={sample_fps:.6f}",
                    "-frames:v",
                    str(count),
                    "-q:v",
                    "3",
                    out,
                ]
            else:
                interval = max(1, (total_frames or count) // count)
                cmd = [
                    ffmpeg,
                    "-y",
                    "-i",
                    src,
                    "-vf",
                    f"select=not(mod(n\\,{interval}))",
                    "-vsync",
                    "0",
                    "-frames:v",
                    str(count),
                    "-q:v",
                    "3",
                    out,
                ]
            kw = no_console_subprocess_kwargs()
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
                check=True,
                **kw,
            )
            return sorted(tmpdir_p.glob(f"{prefix}_*.jpg"))

        if progress_cb:
            progress_cb(0.0, "Plate 프레임 추출 중...")
        plate_files = _extract(plate_path, "plate")
        if progress_cb:
            progress_cb(0.2, "Comp 프레임 추출 중...")
        comp_files = _extract(comp_path, "comp")

        results: List[Tuple[int, bytes, bytes]] = []
        n = min(len(plate_files), len(comp_files))
        for i in range(n):
            if cancelled_cb and cancelled_cb():
                break
            plate_b = _resize_jpeg(plate_files[i].read_bytes())
            comp_b = _resize_jpeg(comp_files[i].read_bytes())
            results.append((i, plate_b, comp_b))

        return results


# ── 메타데이터 비교 (Phase 2) ─────────────────────────────────────────────────


def compare_metadata(
    plate_path: str,
    comp_path: str,
    *,
    ffprobe_bin: Optional[str] = None,
) -> List[MetadataMismatch]:
    """ffprobe로 Plate/Comp 메타데이터 비교. 불일치 항목 목록 반환."""
    ffprobe = ffprobe_bin or resolve_ffprobe()
    if not ffprobe:
        return []

    def _probe(path: str) -> Dict[str, Any]:
        cmd = [
            ffprobe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            path,
        ]
        kw = no_console_subprocess_kwargs()
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30, check=True, **kw)
            return json.loads(r.stdout)
        except Exception as exc:
            logger.debug("ffprobe 실패 (%s): %s", path, exc)
            return {}

    def _video_stream(info: Dict[str, Any]) -> Dict[str, Any]:
        for s in info.get("streams") or []:
            if s.get("codec_type") == "video":
                return s
        return {}

    def _fps_str(s: Dict[str, Any]) -> str:
        for key in ("r_frame_rate", "avg_frame_rate"):
            v = s.get(key, "")
            if v and "/" in v and v != "0/0":
                parts = v.split("/")
                try:
                    val = float(parts[0]) / float(parts[1])
                    return f"{val:.3f}"
                except (ValueError, ZeroDivisionError):
                    pass
        return "?"

    plate_info = _probe(plate_path)
    comp_info = _probe(comp_path)
    ps = _video_stream(plate_info)
    cs = _video_stream(comp_info)

    mismatches: List[MetadataMismatch] = []

    p_fps, c_fps = _fps_str(ps), _fps_str(cs)
    if p_fps != "?" and c_fps != "?" and abs(float(p_fps) - float(c_fps)) > 0.01:
        mismatches.append(MetadataMismatch("FPS", p_fps, c_fps))

    pw, ph = str(ps.get("width", "?")), str(ps.get("height", "?"))
    cw, ch = str(cs.get("width", "?")), str(cs.get("height", "?"))
    if pw != "?" and cw != "?" and (pw != cw or ph != ch):
        mismatches.append(MetadataMismatch("해상도", f"{pw}x{ph}", f"{cw}x{ch}"))

    pf = ps.get("nb_frames") or plate_info.get("format", {}).get("nb_frames")
    cf = cs.get("nb_frames") or comp_info.get("format", {}).get("nb_frames")
    if pf and cf and str(pf) != str(cf):
        mismatches.append(MetadataMismatch("프레임 수", str(pf), str(cf)))

    return mismatches


# ── 시스템 프롬프트 조립 ──────────────────────────────────────────────────────


def build_system_prompt(
    sg_context: Optional[Dict[str, Any]] = None,
    *,
    with_plate_comparison: bool = False,
) -> str:
    """시스템 프롬프트 조립. sg_context에서 step_name, notes를 읽어 동적 삽입."""
    parts: List[str] = [_BASE_SYSTEM_PROMPT]

    if sg_context:
        step = (sg_context.get("step_name") or "").strip().upper()
        for key, extra in STEP_PROMPT_MAP.items():
            if key in step or step in key:
                parts.append(f"\n{extra}")
                break

        notes = sg_context.get("notes") or []
        if notes:
            parts.append(
                "\nRecent supervisor/client notes for this shot (use as specific focus areas):"
            )
            for n in notes:
                body = (n.get("content") or n.get("body") or "").strip()[:200]
                ago = (
                    n.get("created_ago") or n.get("relative_created_at") or n.get("timestamp") or ""
                )
                if body:
                    line = f'- "{body}"'
                    if ago:
                        line += f" ({ago})"
                    parts.append(line)

        manual = sg_context.get("manual_prompt_extra")
        if isinstance(manual, str) and manual.strip():
            parts.append(
                "\nAdditional context from the artist (manual edits, highest priority):\n"
                + manual.strip()
            )

    if with_plate_comparison:
        parts.append(
            "\nYou will receive PAIRS of frames: LEFT = original plate, RIGHT = comp result. "
            "Compare each pair and identify: grain mismatch between plate and comp, "
            "color/tone differences, mask/roto artifacts visible by comparison, "
            "any elements in comp that look different from plate texture or color."
        )

    return "\n".join(parts)


# ── AI 분석 진입점 ────────────────────────────────────────────────────────────


def analyze_frames(
    frames: List[Tuple[int, bytes]],
    settings: AiQcSettings,
    *,
    sg_context: Optional[Dict[str, Any]] = None,
    with_plate_comparison: bool = False,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    cancelled_cb: Optional[Callable[[], bool]] = None,
) -> Tuple[str, List[AiQcIssue]]:
    """프레임들을 AI에 전송해 (verdict, issues) 반환.

    Args:
        frames: [(frame_idx, jpeg_bytes), ...] — extract_sample_frames 결과
        settings: API 공급자/키/모델 설정
        sg_context: Phase 1 SG 컨텍스트 dict (step_name, notes)
        with_plate_comparison: Phase 3 Plate 시각 비교 모드
        progress_cb: (float 0..1, str message) → None
        cancelled_cb: () → bool, True 반환 시 중단

    Returns:
        (verdict, issues) — verdict는 "CONFIRM" 또는 "RETAKE"
    """
    api_key = get_api_key(settings)
    if not api_key:
        raise ValueError(
            "AI API 키가 설정되지 않았습니다.\n"
            "• 다이얼로그에서 API 키를 입력하거나\n"
            "• BPE_AI_QC_API_KEY 환경변수를 설정하세요."
        )

    if cancelled_cb and cancelled_cb():
        return "RETAKE", []

    system_prompt = build_system_prompt(sg_context, with_plate_comparison=with_plate_comparison)

    if progress_cb:
        progress_cb(0.55, "AI에 전송 중...")

    prov = (settings.provider or "").strip().lower()
    if prov == "anthropic":
        verdict, result = _call_anthropic(frames, settings, api_key, system_prompt)
    elif prov == "google":
        verdict, result = _call_google(frames, settings, api_key, system_prompt)
    elif prov == "xai":
        verdict, result = _call_xai(frames, settings, api_key, system_prompt)
    elif prov == "mistral":
        verdict, result = _call_mistral(frames, settings, api_key, system_prompt)
    else:
        verdict, result = _call_openai(frames, settings, api_key, system_prompt)

    if progress_cb:
        progress_cb(0.9, "응답 분석 중...")

    return verdict, result


# ── OpenAI ────────────────────────────────────────────────────────────────────


def _call_openai(
    frames: List[Tuple[int, bytes]],
    settings: AiQcSettings,
    api_key: str,
    system_prompt: str,
) -> Tuple[str, List[AiQcIssue]]:
    model = (settings.model or "gpt-4o").strip()

    content: List[Dict[str, Any]] = [
        {"type": "text", "text": f"다음 {len(frames)}개 프레임을 분석하세요:"},
    ]
    for frame_idx, jpeg_bytes in frames:
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
            }
        )
        content.append({"type": "text", "text": f"(위 이미지: 프레임 인덱스 {frame_idx})"})

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "max_tokens": 2000,
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    resp_text = _http_post(req)
    data = json.loads(resp_text)
    raw = data["choices"][0]["message"]["content"]
    return _parse_result(raw)


# ── Anthropic ─────────────────────────────────────────────────────────────────


def _call_anthropic(
    frames: List[Tuple[int, bytes]],
    settings: AiQcSettings,
    api_key: str,
    system_prompt: str,
) -> Tuple[str, List[AiQcIssue]]:
    model = (settings.model or "claude-opus-4-7-thinking-xhigh").strip()

    user_content: List[Dict[str, Any]] = [
        {"type": "text", "text": f"다음 {len(frames)}개 프레임을 분석하세요:"},
    ]
    for frame_idx, jpeg_bytes in frames:
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        user_content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            }
        )
        user_content.append({"type": "text", "text": f"(위 이미지: 프레임 인덱스 {frame_idx})"})

    payload: Dict[str, Any] = {
        "model": model,
        "max_tokens": 2000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}],
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    resp_text = _http_post(req)
    data = json.loads(resp_text)
    raw = data["content"][0]["text"]
    return _parse_result(raw)


# ── Google Gemini ─────────────────────────────────────────────────────────────


_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _gemini_payload_text(payload: Dict[str, Any]) -> str:
    """generateContent 응답 본문에서 텍스트를 이어붙여 반환."""
    chunks: List[str] = []
    for cand in payload.get("candidates") or []:
        content = cand.get("content") or {}
        for part in content.get("parts") or []:
            t = part.get("text")
            if isinstance(t, str):
                chunks.append(t)
    return "".join(chunks)


def _call_google(
    frames: List[Tuple[int, bytes]],
    settings: AiQcSettings,
    api_key: str,
    system_prompt: str,
) -> Tuple[str, List[AiQcIssue]]:
    model = (settings.model or "gemini-2.5-flash").strip()
    safe_model = model.replace("/", "-")

    parts: List[Dict[str, Any]] = [
        {"text": f"다음 {len(frames)}개 프레임을 분석하세요:"},
    ]
    for frame_idx, jpeg_bytes in frames:
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        parts.append(
            {
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": b64,
                }
            }
        )
        parts.append({"text": f"(위 이미지: 프레임 인덱스 {frame_idx})"})

    payload: Dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"maxOutputTokens": 2000},
    }
    url = f"{_GEMINI_BASE}/{safe_model}:generateContent"
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    resp_text = _http_post(req)
    data = json.loads(resp_text)
    raw = _gemini_payload_text(data)
    return _parse_result(raw)


# ── xAI Grok (Chat Completions) ───────────────────────────────────────────────


def _call_xai(
    frames: List[Tuple[int, bytes]],
    settings: AiQcSettings,
    api_key: str,
    system_prompt: str,
) -> Tuple[str, List[AiQcIssue]]:
    model = (settings.model or "grok-4.3").strip()

    content: List[Dict[str, Any]] = [
        {"type": "text", "text": f"다음 {len(frames)}개 프레임을 분석하세요:"},
    ]
    for frame_idx, jpeg_bytes in frames:
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        uri = f"data:image/jpeg;base64,{b64}"
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": uri, "detail": "auto"},
            }
        )
        content.append({"type": "text", "text": f"(위 이미지: 프레임 인덱스 {frame_idx})"})

    payload: Dict[str, Any] = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "max_tokens": 2000,
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        "https://api.x.ai/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    resp_text = _http_post(req)
    data = json.loads(resp_text)
    raw = data["choices"][0]["message"]["content"]
    if not isinstance(raw, str):
        raw = ""
    return _parse_result(raw)


# ── Mistral (Chat Completions) ────────────────────────────────────────────────


def _call_mistral(
    frames: List[Tuple[int, bytes]],
    settings: AiQcSettings,
    api_key: str,
    system_prompt: str,
) -> Tuple[str, List[AiQcIssue]]:
    model = (settings.model or "pixtral-large-2411").strip()

    content: List[Dict[str, Any]] = [
        {"type": "text", "text": f"다음 {len(frames)}개 프레임을 분석하세요:"},
    ]
    for frame_idx, jpeg_bytes in frames:
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        uri = f"data:image/jpeg;base64,{b64}"
        content.append({"type": "image_url", "image_url": uri})
        content.append({"type": "text", "text": f"(위 이미지: 프레임 인덱스 {frame_idx})"})

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "max_tokens": 2000,
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        "https://api.mistral.ai/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    resp_text = _http_post(req)
    data = json.loads(resp_text)
    raw = data["choices"][0]["message"]["content"]
    if not isinstance(raw, str):
        raw = ""
    return _parse_result(raw)


# ── HTTP 헬퍼 ─────────────────────────────────────────────────────────────────


def _http_post(req: Request) -> str:
    """HTTP POST 실행. 오류 시 사람이 읽기 쉬운 예외 발생."""
    try:
        with urlopen(req, timeout=120) as resp:
            return resp.read().decode("utf-8")
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        code = exc.code
        if code == 401:
            raise ValueError(f"API 인증 실패 (401). API 키를 확인하세요.\n상세: {body}") from exc
        if code == 403:
            raise ValueError(
                f"API 접근 거부 (403). 권한 또는 플랜을 확인하세요.\n상세: {body}"
            ) from exc
        if code == 429:
            raise RuntimeError(
                f"API 요청 한도 초과 (429). 잠시 후 다시 시도하세요.\n상세: {body}"
            ) from exc
        raise RuntimeError(f"API 오류 ({code}): {body}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"인터넷 연결 오류: {exc.reason}\n• 인터넷 연결 상태 또는 방화벽 설정을 확인하세요."
        ) from exc


# ── 응답 파싱 ─────────────────────────────────────────────────────────────────


def _parse_issues(text: str) -> List[AiQcIssue]:
    """AI 응답 텍스트에서 JSON 배열을 파싱해 AiQcIssue 목록 반환. 실패 시 빈 목록."""
    text = text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        logger.warning("AI 응답에서 JSON 배열 없음: %.200s", text)
        return []
    try:
        items = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.warning("AI 응답 JSON 파싱 실패: %s | 응답: %.200s", exc, text)
        return []

    results: List[AiQcIssue] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        frame = int(item.get("frame", 0))
        severity = str(item.get("severity", "MED")).upper().strip()
        if severity not in ("HIGH", "MED", "LOW"):
            severity = "MED"
        note = str(item.get("note", "")).strip()
        if note:
            results.append(AiQcIssue(frame=frame, severity=severity, note=note))
    return results


def _parse_result(text: str) -> Tuple[str, List[AiQcIssue]]:
    """AI 응답 텍스트에서 (verdict, issues) 파싱.

    우선 JSON 객체 {"verdict": ..., "issues": [...]} 형식을 시도하고,
    실패 시 JSON 배열 형식(하위 호환)으로 폴백한 뒤 휴리스틱으로 verdict 결정.
    """
    text = text.strip()

    # JSON 객체 형식 시도
    obj_start = text.find("{")
    if obj_start != -1:
        obj_end = text.rfind("}")
        if obj_end > obj_start:
            try:
                obj = json.loads(text[obj_start : obj_end + 1])
                if isinstance(obj, dict) and "issues" in obj:
                    verdict = str(obj.get("verdict") or "RETAKE").strip().upper()
                    if verdict not in ("CONFIRM", "RETAKE"):
                        verdict = "RETAKE"
                    issues = _parse_issues(json.dumps(obj.get("issues") or []))
                    return verdict, issues
            except json.JSONDecodeError:
                pass

    # 폴백: 배열 형식
    issues = _parse_issues(text)
    has_high = any(i.severity == "HIGH" for i in issues)
    verdict = "RETAKE" if (has_high or issues) else "CONFIRM"
    return verdict, issues
