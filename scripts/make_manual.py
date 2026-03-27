"""BPE 비주얼 가이드 PDF — UI 목업·다이어그램 중심 (reportlab Drawing)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Tuple

from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.colors import Color
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ── 버전 (VERSION.txt) ────────────────────────────────────────────────────────
def _read_version() -> str:
    root = Path(__file__).resolve().parent.parent
    p = root / "VERSION.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    return "0.8.2"


VERSION = _read_version()

# ── 폰트 ──────────────────────────────────────────────────────────────────────
_FONT_DIRS = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
    Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts",
]


def _find_font(names: List[str]) -> Path | None:
    for name in names:
        for d in _FONT_DIRS:
            p = d / name
            if p.exists():
                return p
    return None


def _register_fonts() -> Tuple[str, str]:
    reg = _find_font(["malgun.ttf", "NanumGothic.ttf", "gulim.ttc"])
    bold = _find_font(["malgunbd.ttf", "NanumGothicBold.ttf", "gulim.ttc"])
    if reg and bold:
        pdfmetrics.registerFont(TTFont("KR", str(reg)))
        pdfmetrics.registerFont(TTFont("KR-Bold", str(bold)))
        return "KR", "KR-Bold"
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = _register_fonts()

# ── 색상 ───────────────────────────────────────────────────────────────────────
C_BG = colors.HexColor("#1A1A1A")
C_PANEL = colors.HexColor("#252525")
C_ACCENT = colors.HexColor("#E87D0D")
C_BORDER = colors.HexColor("#444444")
C_TEXT = colors.HexColor("#E0E0E0")
C_DIM = colors.HexColor("#888888")
C_WHITE = colors.white
C_GREEN = colors.HexColor("#2D6A4F")
C_RED = colors.HexColor("#9B2226")
C_BLUE = colors.HexColor("#1D3557")
C_WARN = colors.HexColor("#FFB703")

W_PAGE, H_PAGE = A4
MARGIN = 18 * mm
CONTENT_W = W_PAGE - 2 * MARGIN


# ── Paragraph 스타일 ─────────────────────────────────────────────────────────
def _p(name: str, **kw: Any) -> ParagraphStyle:
    return ParagraphStyle(name, fontName=FONT, **kw)


def _pb(name: str, **kw: Any) -> ParagraphStyle:
    return ParagraphStyle(name, fontName=FONT_BOLD, **kw)


S_TITLE = _pb("t", fontSize=22, textColor=C_ACCENT, leading=28, spaceAfter=8)
S_H1 = _pb("h1", fontSize=14, textColor=C_ACCENT, leading=20, spaceBefore=10, spaceAfter=6)
S_BODY = _p("b", fontSize=9.5, textColor=C_TEXT, leading=14, spaceAfter=4)
S_CAP = _p("c", fontSize=8, textColor=C_DIM, leading=11, alignment=TA_CENTER)
S_SMALL = _p("s", fontSize=8, textColor=C_TEXT, leading=12)


def P(text: str, style: ParagraphStyle = S_BODY) -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), style)


def SP(h: float = 6) -> Spacer:
    return Spacer(1, h)


# ── Drawing → Flowable ─────────────────────────────────────────────────────────


class DrawingFlowable(Flowable):
    """reportlab Drawing을 페이지에 삽입."""

    def __init__(self, drawing: Drawing) -> None:
        self.drawing = drawing
        self.width = drawing.width
        self.height = drawing.height

    def draw(self) -> None:
        renderPDF.draw(self.drawing, self.canv, 0, 0)


def _rect(
    x: float,
    y: float,
    w: float,
    h: float,
    fill: Color,
    stroke: Color | None = None,
    sw: float = 0.5,
) -> Rect:
    r = Rect(x, y, w, h, fillColor=fill, strokeColor=stroke or fill, strokeWidth=sw)
    return r


def _txt(
    x: float,
    y: float,
    text: str,
    size: float = 8,
    bold: bool = False,
    color: Color = C_TEXT,
) -> String:
    return String(
        x,
        y,
        text,
        fontName=FONT_BOLD if bold else FONT,
        fontSize=size,
        fillColor=color,
    )


def _arrow_h(d: Drawing, x1: float, y: float, x2: float, color: Color = C_ACCENT) -> None:
    d.add(Line(x1, y, x2, y, strokeColor=color, strokeWidth=1.2))
    # 삼각형 머리
    d.add(Line(x2 - 5, y + 3, x2, y, strokeColor=color, strokeWidth=1.2))
    d.add(Line(x2 - 5, y - 3, x2, y, strokeColor=color, strokeWidth=1.2))


def _arrow_v(d: Drawing, x: float, y1: float, y2: float, color: Color = C_ACCENT) -> None:
    d.add(Line(x, y1, x, y2, strokeColor=color, strokeWidth=1.2))
    d.add(Line(x - 3, y2 + 5, x, y2, strokeColor=color, strokeWidth=1.2))
    d.add(Line(x + 3, y2 + 5, x, y2, strokeColor=color, strokeWidth=1.2))


# ── 그래픽: 표지 ───────────────────────────────────────────────────────────────


def draw_cover() -> Drawing:
    w, h = CONTENT_W, 320
    d = Drawing(w, h)
    d.add(_rect(0, 0, w, h, C_BG))
    d.add(_rect(0, h - 10, w, 10, C_ACCENT))
    d.add(_txt(w / 2 - 80, h - 55, "BELUCA Pipeline Engine", 18, True, C_WHITE))
    d.add(_txt(w / 2 - 95, h - 85, "VFX 작업자를 위한 BPE 사용 가이드", 11, False, C_DIM))
    d.add(_txt(w / 2 - 35, h - 120, f"v{VERSION}", 10, False, C_ACCENT))
    d.add(_rect(40, 40, w - 80, 1, C_BORDER))
    d.add(_txt(40, 25, "ShotGrid · Nuke · 팀 프리셋", 9, False, C_DIM))
    return d


# ── BPE 한눈에 (Before / After + 탭) ───────────────────────────────────────────


def draw_overview() -> Drawing:
    w, h = CONTENT_W, 280
    d = Drawing(w, h)
    d.add(_rect(0, 0, w, h, C_BG))

    box_w = (w - 24) / 2
    y0 = h - 30

    # Left: without BPE
    d.add(_txt(12, y0, "기존: 탐색기·경로·버전을 직접 찾기", 9, True, C_DIM))
    lx = 12
    ly = y0 - 28
    steps = ["탐색기", "프로젝트", "에피소드", "샷", "nuke", "버전", "Nuke"]
    for i, s in enumerate(steps):
        d.add(_rect(lx + i * (box_w / 7 - 2), ly, box_w / 7 - 4, 22, C_PANEL, C_BORDER))
        d.add(_txt(lx + i * (box_w / 7 - 2) + 2, ly + 8, s, 6.5, False, C_TEXT))
        if i < len(steps) - 1:
            x_end = lx + (i + 1) * (box_w / 7 - 4)
            _arrow_h(d, x_end - 8, ly + 11, x_end, C_WARN)

    d.add(_txt(lx, ly - 22, "컷마다 반복 · 경로 실수 가능", 8, False, C_WARN))

    # Right: with BPE
    rx = 12 + box_w + 12
    d.add(_txt(rx, y0, "BPE: 조회 후 버튼 한 번", 9, True, C_ACCENT))
    d.add(_rect(rx, ly, box_w / 2 - 8, 28, C_GREEN, C_ACCENT))
    d.add(_txt(rx + 8, ly + 10, "조회", 9, True, C_WHITE))
    _arrow_h(d, rx + box_w / 2 - 8 + 4, ly + 14, rx + box_w / 2 + 20, C_ACCENT)
    d.add(_rect(rx + box_w / 2 + 24, ly, box_w / 2 - 8, 28, C_BLUE, C_ACCENT))
    d.add(_txt(rx + box_w / 2 + 32, ly + 6, "폴더 열기 /", 7, True, C_WHITE))
    d.add(_txt(rx + box_w / 2 + 32, ly - 2, "NukeX", 7, True, C_WHITE))
    d.add(_txt(rx, ly - 22, "동일 결과를 더 짧은 단계로", 8, False, C_GREEN))

    # Tabs row
    ty = 50
    tabs = [
        ("My Tasks", "배정 샷 · 폴더 · Nuke · 퍼블리쉬"),
        ("Preset Manager", "FPS·OCIO·Write 팀 표준"),
        ("Tools", "QC · 렌더 후 미리보기"),
    ]
    tw = (w - 24) / 3
    for i, (name, desc) in enumerate(tabs):
        x = 12 + i * tw
        d.add(_rect(x, ty + 20, tw - 6, 36, C_PANEL, C_BORDER))
        d.add(_txt(x + 6, ty + 42, name, 8, True, C_ACCENT))
        d.add(_txt(x + 6, ty + 28, desc, 6.5, False, C_DIM))
    d.add(_txt(12, ty + 12, "왼쪽 사이드바 탭", 8, True, C_TEXT))
    return d


# ── My Tasks: 수작업 vs BPE (Before/After 상세) ────────────────────────────────


def draw_my_tasks_compare() -> Drawing:
    w, h = CONTENT_W, 300
    d = Drawing(w, h)
    d.add(_rect(0, 0, w, h, C_BG))

    d.add(_txt(12, h - 22, "샷 작업 폴더·최신 NK까지 가는 과정", 10, True, C_WHITE))

    # Manual column
    mx = 12
    my = h - 48
    mh = 22
    manual_steps = [
        "서버 드라이브 열기",
        "프로젝트 폴더 이동",
        "시퀀스 · 에피소드 · 샷 폴더 순서로 이동",
        "comp / devl / nuke",
        "폴더 안에서 최신 .nk 찾기",
        "Nuke에서 해당 파일 열기",
    ]
    d.add(_txt(mx, my + 8, "수동으로 할 때", 8, True, C_WARN))
    y = my - 5
    for i, s in enumerate(manual_steps):
        d.add(_rect(mx, y - i * (mh + 4), w / 2 - 20, mh, C_PANEL, C_BORDER))
        d.add(_txt(mx + 6, y - i * (mh + 4) + 8, f"{i + 1}. {s}", 7, False, C_TEXT))
        if i < len(manual_steps) - 1:
            cx = mx + (w / 2 - 20) / 2
            y_top = y - i * (mh + 4) - 2
            y_bot = y - (i + 1) * (mh + 4) + mh
            _arrow_v(d, cx, y_top, y_bot, C_WARN)

    d.add(
        _txt(
            mx,
            y - len(manual_steps) * (mh + 4) - 8,
            "컷마다 수 분 ~ 십여 분 · 실수 여지 있음",
            7,
            False,
            C_DIM,
        )
    )

    # BPE column
    bx = w / 2 + 8
    d.add(_txt(bx, my + 8, "BPE My Tasks", 8, True, C_ACCENT))
    d.add(_rect(bx, my - 10, w / 2 - 20, 32, C_GREEN, C_ACCENT))
    d.add(_txt(bx + 8, my + 2, "조회 (담당자·프로젝트)", 8, True, C_WHITE))
    _arrow_v(d, bx + (w / 2 - 20) / 2, my - 12, my - 38, C_ACCENT)
    d.add(_rect(bx, my - 52, w / 2 - 20, 50, C_BLUE, C_ACCENT))
    d.add(_txt(bx + 8, my - 22, "샷 카드에서", 7, True, C_WHITE))
    d.add(_txt(bx + 8, my - 34, "[폴더 열기]  탐색기로 작업 경로", 6.5, False, C_TEXT))
    d.add(_txt(bx + 8, my - 46, "[NukeX]  최신 NK를 NukeX로", 6.5, False, C_TEXT))
    d.add(_txt(bx, my - 68, "경로 타이핑·버전 비교 최소화", 7, False, C_GREEN))
    return d


# ── 필터 바 + 샷 카드 목업 ─────────────────────────────────────────────────────


def draw_filter_and_card() -> Drawing:
    w, h = CONTENT_W, 260
    d = Drawing(w, h)
    d.add(_rect(0, 0, w, h, C_BG))

    y = h - 28
    d.add(_txt(12, y, "My Tasks 화면 구성", 10, True, C_WHITE))

    # Filter bar
    fy = h - 58
    d.add(_rect(12, fy, 90, 22, C_PANEL, C_BORDER))
    d.add(_txt(18, fy + 8, "프로젝트 ▼", 7, False, C_TEXT))
    d.add(_rect(110, fy, 100, 22, C_PANEL, C_BORDER))
    d.add(_txt(116, fy + 8, "담당자 이름", 7, False, C_TEXT))
    d.add(_rect(220, fy, 58, 22, C_PANEL, C_BORDER))
    d.add(_txt(228, fy + 8, "나로 설정", 6.5, False, C_DIM))
    d.add(_rect(290, fy, 52, 22, C_PANEL, C_BORDER))
    d.add(_txt(298, fy + 8, "상태 ▼", 6.5, False, C_TEXT))
    d.add(_rect(352, fy, 48, 22, C_ACCENT, C_ACCENT))
    d.add(_txt(360, fy + 8, "조회", 7, True, C_WHITE))

    d.add(_txt(12, fy - 18, "↑ 한 번 설정 후 조회하면 목록이 채워짐", 7, False, C_DIM))

    # Shot card
    cy = fy - 52
    d.add(_rect(12, cy, w - 24, 68, C_PANEL, C_BORDER))
    # thumb
    d.add(_rect(18, cy + 8, 72, 52, colors.HexColor("#333333"), C_BORDER))
    d.add(_txt(38, cy + 28, "IMG", 8, False, C_DIM))
    d.add(Line(98, cy + 8, 98, cy + 60, strokeColor=C_BORDER))
    d.add(_txt(104, cy + 48, "E107_S022_0080", 8, True, C_ACCENT))
    d.add(_txt(104, cy + 36, "Task: comp", 7, False, C_TEXT))
    d.add(_txt(104, cy + 24, "Version: v012", 7, False, C_DIM))
    # status cell
    d.add(_rect(280, cy + 8, 52, 52, colors.HexColor("#F0A0C0"), C_BORDER))
    d.add(_txt(290, cy + 38, "wip", 8, True, colors.HexColor("#111111")))
    # buttons
    bx = 345
    d.add(_rect(bx, cy + 38, 62, 18, C_BLUE, C_BORDER))
    d.add(_txt(bx + 8, cy + 42, "폴더 열기", 6.5, True, C_WHITE))
    d.add(_rect(bx, cy + 14, 50, 18, C_GREEN, C_BORDER))
    d.add(_txt(bx + 10, cy + 18, "NukeX", 6.5, True, C_WHITE))

    d.add(
        _txt(
            12,
            cy - 16,
            "폴더 열기: comp/devl/nuke 등 작업 경로를 탐색기로 연다",
            7,
            False,
            C_DIM,
        )
    )
    d.add(
        _txt(
            12,
            cy - 28,
            "NukeX: 최신 .nk를 NukeX로 연다 (서버·Nuke 설치 필요)",
            7,
            False,
            C_DIM,
        )
    )
    return d


# ── 퍼블리쉬 창 목업 ───────────────────────────────────────────────────────────


def draw_publish() -> Drawing:
    w, h = CONTENT_W, 220
    d = Drawing(w, h)
    d.add(_rect(0, 0, w, h, C_BG))

    d.add(_txt(12, h - 22, "퍼블리쉬 (Version 업로드)", 10, True, C_WHITE))

    # Window
    d.add(_rect(40, 40, w - 80, h - 75, C_PANEL, C_ACCENT))
    d.add(_txt(50, h - 88, "MOV 파일을 여기에 놓거나 경로 입력", 8, False, C_DIM))
    d.add(_rect(50, h - 118, w - 100, 24, colors.HexColor("#333"), C_BORDER))
    d.add(_txt(56, h - 108, "Shot / Task / Artist 선택 → Create Version", 7, False, C_TEXT))

    # Flow below
    fy = 35
    d.add(_rect(50, fy + 40, 70, 22, C_GREEN, C_BORDER))
    d.add(_txt(58, fy + 46, "MOV 준비", 7, True, C_WHITE))
    _arrow_h(d, 125, fy + 51, 145, C_ACCENT)
    d.add(_rect(150, fy + 40, 90, 22, C_PANEL, C_BORDER))
    d.add(_txt(158, fy + 46, "샷·태스크 확인", 7, False, C_TEXT))
    _arrow_h(d, 245, fy + 51, 265, C_ACCENT)
    d.add(_rect(270, fy + 40, 100, 22, C_ACCENT, C_ACCENT))
    d.add(_txt(288, fy + 46, "Create Version", 7, True, C_WHITE))

    d.add(
        _txt(
            50,
            fy + 18,
            "ShotGrid에 올라가며 필요 시 태스크 상태도 갱신",
            7,
            False,
            C_DIM,
        )
    )
    return d


# ── Preset: Before/After (팀) ──────────────────────────────────────────────────


def draw_preset_team() -> Drawing:
    w, h = CONTENT_W, 270
    d = Drawing(w, h)
    d.add(_rect(0, 0, w, h, C_BG))

    d.add(
        _txt(
            12,
            h - 22,
            "프리셋이 없을 때 / 있을 때 (PD·실장·파이프라인)",
            9,
            True,
            C_WHITE,
        )
    )

    # Before
    d.add(_txt(12, h - 48, "Before: 설정이 사람마다 다름", 8, True, C_WARN))
    for i in range(3):
        x = 20 + i * 95
        d.add(_rect(x, h - 100, 85, 55, C_PANEL, C_BORDER))
        d.add(_txt(x + 25, h - 58, f"작업자{i + 1}", 7, True, C_DIM))
        d.add(_txt(x + 8, h - 72, "FPS 24?", 6, False, C_WARN))
        d.add(_txt(x + 8, h - 82, "OCIO 경로 다름", 6, False, C_WARN))

    # After
    d.add(_txt(12, h - 125, "After: 프리셋 하나로 팀 기준 통일", 8, True, C_GREEN))
    d.add(_rect(20, h - 195, 100, 40, C_ACCENT, C_ACCENT))
    d.add(_txt(35, h - 175, "리드가 저장", 8, True, C_WHITE))
    _arrow_h(d, 125, h - 175, 155, C_ACCENT)
    d.add(_rect(160, h - 195, 120, 40, C_BLUE, C_BORDER))
    d.add(_txt(175, h - 178, "공유 폴더", 8, True, C_WHITE))
    _arrow_h(d, 285, h - 175, 315, C_ACCENT)
    d.add(_rect(320, h - 195, w - 340, 40, C_GREEN, C_BORDER))
    d.add(_txt(330, h - 178, "전원 동일 프리셋 로드", 7, True, C_WHITE))

    d.add(
        _txt(
            12,
            h - 215,
            "신규 투입 시에도 한 문장으로 기준을 전달 가능",
            7,
            False,
            C_DIM,
        )
    )
    d.add(_txt(12, h - 228, "Write 해상도·컬러 실수·납품 포맷 혼선 감소", 7, False, C_DIM))
    return d


# ── Preset Manager UI 목업 ─────────────────────────────────────────────────────


def draw_preset_ui() -> Drawing:
    w, h = CONTENT_W, 240
    d = Drawing(w, h)
    d.add(_rect(0, 0, w, h, C_BG))

    d.add(_txt(12, h - 22, "Preset Manager — 프리셋 만들기·저장", 10, True, C_WHITE))

    # Left form
    d.add(_rect(12, 30, w / 2 - 18, h - 55, C_PANEL, C_BORDER))
    d.add(_txt(22, h - 48, "프로젝트 코드 · FPS · 해상도", 7, True, C_ACCENT))
    d.add(_txt(22, h - 62, "OCIO 경로 · Read / Write", 7, False, C_DIM))
    d.add(_rect(22, h - 95, w / 2 - 42, 14, colors.HexColor("#333"), C_BORDER))
    d.add(_rect(22, h - 115, w / 2 - 42, 14, colors.HexColor("#333"), C_BORDER))

    # Right list
    d.add(_rect(w / 2 + 6, 30, w / 2 - 18, h - 55, C_PANEL, C_BORDER))
    d.add(_txt(w / 2 + 14, h - 48, "저장된 프리셋", 7, True, C_ACCENT))
    for i in range(4):
        d.add(_rect(w / 2 + 14, h - 68 - i * 18, w / 2 - 36, 14, colors.HexColor("#333"), C_BORDER))
        d.add(_txt(w / 2 + 20, h - 64 - i * 18, f"프로젝트_{i + 1}", 6.5, False, C_TEXT))

    d.add(
        _txt(
            12,
            18,
            "저장 위치를 팀 공유 경로로 맞추면 목록이 전원에게 동일",
            7,
            False,
            C_DIM,
        )
    )
    return d


# ── Shot Builder ───────────────────────────────────────────────────────────────


def draw_shot_builder() -> Drawing:
    w, h = CONTENT_W, 230
    d = Drawing(w, h)
    d.add(_rect(0, 0, w, h, C_BG))

    d.add(_txt(12, h - 22, "Shot Builder — 새 샷 v001 NK 생성", 10, True, C_WHITE))

    fields = ["서버 루트", "프로젝트 코드", "샷 이름", "프리셋"]
    fx = 12
    fy = h - 50
    for i, name in enumerate(fields):
        d.add(_rect(fx, fy - i * 28, 140, 20, C_PANEL, C_BORDER))
        d.add(_txt(fx + 6, fy - i * 28 + 6, name, 7, False, C_DIM))

    d.add(_rect(160, fy - 10, 70, 22, C_ACCENT, C_ACCENT))
    d.add(_txt(175, fy - 4, "NK 생성", 7, True, C_WHITE))

    # Tree
    d.add(_txt(12, fy - 100, "생성 예 (팀 규칙에 맞는 경로)", 8, True, C_DIM))
    tree = "…/샷폴더/comp/devl/nuke/v001/샷_comp_v001.nk"
    d.add(_txt(12, fy - 118, tree, 7, False, C_GREEN))

    d.add(_rect(12, 25, w - 24, 28, colors.HexColor("#3d2f00"), C_WARN))
    d.add(_txt(18, 35, "이미 v001 NK가 있으면 덮어쓰지 않음 (기존 작업 보호)", 7, True, C_WARN))
    return d


# ── Tools ──────────────────────────────────────────────────────────────────────


def draw_tools() -> Drawing:
    w, h = CONTENT_W, 200
    d = Drawing(w, h)
    d.add(_rect(0, 0, w, h, C_BG))

    d.add(_txt(12, h - 22, "Tools — Nuke에서 쓰는 옵션", 10, True, C_WHITE))

    cards = [
        ("QC Checker", "Write 렌더 전\nFPS·해상도·OCIO 점검"),
        ("Post-Render Viewer", "렌더 후 결과 Read 자동"),
    ]
    cw = (w - 36) / 2
    for i, (title, desc) in enumerate(cards):
        x = 12 + i * (cw + 12)
        d.add(_rect(x, h - 100, cw, 70, C_PANEL, C_BORDER))
        d.add(_txt(x + 8, h - 38, title, 8, True, C_ACCENT))
        d.add(_txt(x + 8, h - 58, desc.replace("\n", " "), 7, False, C_DIM))

    d.add(
        _txt(
            12,
            h - 115,
            "Tools 탭 ON 후 Nuke: setup_pro → BPE Tools → Reload Tool Hooks",
            7,
            False,
            C_DIM,
        )
    )
    return d


# ── 치트시트 표 ────────────────────────────────────────────────────────────────


def cheat_sheet_table() -> Table:
    data = [
        [
            Paragraph("상황", _pb("h", fontSize=9, textColor=C_ACCENT)),
            Paragraph("이 기능", _pb("h", fontSize=9, textColor=C_ACCENT)),
        ],
        [
            Paragraph("내 배정 샷 목록·폴더·Nuke 한 번에", S_BODY),
            Paragraph("My Tasks → 조회 → 카드 버튼", S_BODY),
        ],
        [
            Paragraph("MOV를 ShotGrid Version으로", S_BODY),
            Paragraph("카드 <b>퍼블리쉬</b> 또는 퍼블리쉬 화면", S_BODY),
        ],
        [
            Paragraph("팀과 같은 FPS·OCIO·Write 기준", S_BODY),
            Paragraph("Preset Manager + 공유 폴더", S_BODY),
        ],
        [
            Paragraph("새 샷 첫 NK(v001)", S_BODY),
            Paragraph("Shot Builder (My Tasks 우측 패널 가능)", S_BODY),
        ],
        [
            Paragraph("렌더 전 스펙 체크", S_BODY),
            Paragraph("Tools → QC Checker (Nuke 연동)", S_BODY),
        ],
    ]
    t = Table(data, colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.58])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), C_PANEL),
                ("TEXTCOLOR", (0, 0), (-1, 0), C_ACCENT),
                ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


# ── 페이지 훅 ───────────────────────────────────────────────────────────────────


def _on_page(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFillColor(C_BG)
    canvas.rect(0, 0, W_PAGE, H_PAGE, fill=1, stroke=0)
    canvas.setFillColor(C_ACCENT)
    canvas.rect(0, H_PAGE - 6, W_PAGE, 6, fill=1, stroke=0)
    canvas.setFont(FONT, 8)
    canvas.setFillColor(C_DIM)
    canvas.drawString(MARGIN, H_PAGE - 4 * mm, "BPE 사용 가이드")
    canvas.drawRightString(W_PAGE - MARGIN, 12, f"v{VERSION}")
    canvas.restoreState()


def _on_first_page(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFillColor(C_BG)
    canvas.rect(0, 0, W_PAGE, H_PAGE, fill=1, stroke=0)
    canvas.setFillColor(C_ACCENT)
    canvas.rect(0, H_PAGE - 8, W_PAGE, 8, fill=1, stroke=0)
    canvas.rect(0, 0, W_PAGE, 8, fill=1, stroke=0)
    canvas.restoreState()


# ── main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "BPE_manual.pdf"
    story: List[Any] = []

    # 표지
    story.append(SP(8))
    story.append(DrawingFlowable(draw_cover()))
    story.append(SP(12))

    # 1. 한눈에
    story.append(P("1. BPE 한눈에", S_TITLE))
    story.append(DrawingFlowable(draw_overview()))
    story.append(SP(8))
    story.append(
        P(
            "왼쪽은 서버 안에서 폴더를 따라가며 파일을 찾는 일반적인 단계이고, "
            "오른쪽은 BPE에서 조회한 뒤 버튼으로 같은 목적을 처리하는 흐름입니다.",
            S_BODY,
        )
    )
    story.append(PageBreak())

    # 2. My Tasks 비교
    story.append(P("2. My Tasks — 폴더·최신 NK까지", S_TITLE))
    story.append(DrawingFlowable(draw_my_tasks_compare()))
    story.append(SP(6))
    story.append(
        P(
            "서버 구조가 길수록 탐색에 걸리는 시간이 늘고, 잘못된 폴더를 연 경우도 생깁니다. "
            "My Tasks는 ShotGrid에 맞춰 샷 단위로 바로 연결합니다.",
            S_BODY,
        )
    )
    story.append(PageBreak())

    story.append(P("2-1. 화면에서 쓰는 위치", S_TITLE))
    story.append(DrawingFlowable(draw_filter_and_card()))
    story.append(PageBreak())

    # 3. 퍼블리쉬
    story.append(P("3. 퍼블리쉬", S_TITLE))
    story.append(DrawingFlowable(draw_publish()))
    story.append(
        P(
            "카드의 <b>퍼블리쉬</b>로 창을 열고, MOV를 넣은 뒤 Shot·Task를 맞추고 업로드합니다.",
            S_BODY,
        )
    )
    story.append(PageBreak())

    # 4. Preset 팀
    story.append(P("4. Preset Manager — 팀 기준 맞추기", S_TITLE))
    story.append(DrawingFlowable(draw_preset_team()))
    story.append(SP(8))
    story.append(DrawingFlowable(draw_preset_ui()))
    story.append(
        P(
            "프리셋 저장 폴더를 팀이 쓰는 네트워크 경로로 통일하면, "
            "목록과 내용이 모두 같은 기준으로 보입니다.",
            S_BODY,
        )
    )
    story.append(PageBreak())

    # 5. Shot Builder
    story.append(P("5. Shot Builder", S_TITLE))
    story.append(DrawingFlowable(draw_shot_builder()))
    story.append(PageBreak())

    # 6. Tools
    story.append(P("6. Tools", S_TITLE))
    story.append(DrawingFlowable(draw_tools()))
    story.append(PageBreak())

    # 7. 치트시트
    story.append(P("빠른 참고", S_TITLE))
    story.append(cheat_sheet_table())
    story.append(SP(16))
    story.append(
        P(
            "서버 드라이브가 연결되어 있어야 <b>폴더 열기</b>·<b>NukeX</b>가 동작합니다. "
            "Nuke는 PC에 설치되어 있어야 합니다.",
            S_BODY,
        )
    )

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 8,
        bottomMargin=MARGIN + 10,
        title="BPE 사용 가이드",
        author="BELUCA",
    )
    doc.build(story, onFirstPage=_on_first_page, onLaterPages=_on_page)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
