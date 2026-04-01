"""BPE_User_Guide.md → BPE_User_Guide.pdf
커버 페이지 + 목차 + 헤더/푸터 + 페이지 번호 포함 공문서 스타일.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, List, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

HERE = os.path.dirname(os.path.abspath(__file__))
MD_FILE = os.path.join(HERE, "BPE_User_Guide.md")
PDF_FILE = os.path.join(HERE, "BPE_User_Guide.pdf")

# ── 브랜드 컬러 ──────────────────────────────────────────────────
C_DARK = colors.HexColor("#0d2b45")   # 커버 배경 / H2
C_MID  = colors.HexColor("#1a4a72")   # H3, 표 헤더
C_LITE = colors.HexColor("#cce0f5")   # 구분선
C_ROW  = colors.HexColor("#f2f7fc")   # 표 짝수행
C_GRAY = colors.HexColor("#888888")   # 헤더/푸터

PAGE_W, PAGE_H = A4
MARGIN_L = 2.3 * cm
MARGIN_R = 2.3 * cm
MARGIN_T = 2.5 * cm
MARGIN_B = 2.0 * cm
HEADER_H = 1.0 * cm
FOOTER_H = 1.0 * cm

FONT      = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


# ── 폰트 등록 ────────────────────────────────────────────────────

def register_fonts() -> None:
    global FONT, FONT_BOLD
    regular = [
        (r"C:\Windows\Fonts\malgun.ttf",      "BPEFont"),
        (r"C:\Windows\Fonts\NanumGothic.ttf", "BPEFont"),
    ]
    bold = [
        (r"C:\Windows\Fonts\malgunbd.ttf",        "BPEFontB"),
        (r"C:\Windows\Fonts\NanumGothicBold.ttf",  "BPEFontB"),
    ]
    for path, name in regular:
        if os.path.isfile(path):
            pdfmetrics.registerFont(TTFont(name, path))
            FONT = name
            print(f"  [폰트]      {name} <- {path}")
            break
    for path, name in bold:
        if os.path.isfile(path):
            pdfmetrics.registerFont(TTFont(name, path))
            FONT_BOLD = name
            print(f"  [폰트 볼드] {name} <- {path}")
            break
    if FONT == "Helvetica":
        print("경고: 한글 폰트를 찾지 못했습니다.")
        sys.exit(1)


# ── 인라인 마크업 변환 ───────────────────────────────────────────

def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def _inline(text: str) -> str:
    """`코드` 와 **굵게** 를 ReportLab XML로 변환."""
    parts: List[str] = []
    pos = 0
    for m in re.finditer(r"`([^`]+)`", text):
        parts.append(_esc(text[pos:m.start()]))
        parts.append(
            f'<font name="Courier" size="8" color="#444444">{_esc(m.group(1))}</font>'
        )
        pos = m.end()
    parts.append(_esc(text[pos:]))
    s = "".join(parts)

    # **bold** 처리
    out: List[str] = []
    i = 0
    while True:
        a = s.find("**", i)
        if a == -1:
            out.append(s[i:])
            break
        b = s.find("**", a + 2)
        if b == -1:
            out.append(s[i:])
            break
        out.append(s[i:a])
        inner = s[a + 2 : b]
        out.append(f'<font name="{FONT_BOLD}"><b>{inner}</b></font>')
        i = b + 2
    return "".join(out)


# ── 스타일 팩토리 ────────────────────────────────────────────────

def make_styles() -> Dict[str, ParagraphStyle]:
    def S(name: str, **kw: Any) -> ParagraphStyle:
        return ParagraphStyle(name=name, **kw)

    return {
        # ── 커버 ──
        "cover_title": S(
            "CoverTitle",
            fontName=FONT_BOLD, fontSize=30, leading=38,
            textColor=colors.white, alignment=TA_LEFT, spaceAfter=4,
        ),
        "cover_sub": S(
            "CoverSub",
            fontName=FONT, fontSize=14, leading=20,
            textColor=colors.HexColor("#b0cce8"), alignment=TA_LEFT, spaceAfter=6,
        ),
        "cover_badge": S(
            "CoverBadge",
            fontName=FONT_BOLD, fontSize=10, leading=14,
            textColor=C_DARK, alignment=TA_LEFT,
        ),
        "cover_desc": S(
            "CoverDesc",
            fontName=FONT, fontSize=9, leading=14,
            textColor=colors.HexColor("#c8dff0"), alignment=TA_LEFT, spaceAfter=4,
        ),
        "cover_version": S(
            "CoverVersion",
            fontName=FONT, fontSize=8.5, leading=12,
            textColor=colors.HexColor("#8aafc8"), alignment=TA_LEFT,
        ),
        # ── 본문 H2 / H3 ──
        "h2": S(
            "H2",
            fontName=FONT_BOLD, fontSize=14, leading=20,
            textColor=C_DARK,
            spaceBefore=4, spaceAfter=10,
        ),
        "h3": S(
            "H3",
            fontName=FONT_BOLD, fontSize=11, leading=16,
            textColor=C_MID,
            spaceBefore=14, spaceAfter=6,
        ),
        # ── 본문 ──
        "body": S(
            "Body",
            fontName=FONT, fontSize=10, leading=16,
            alignment=TA_LEFT, spaceAfter=8,
        ),
        "quote": S(
            "Quote",
            fontName=FONT, fontSize=10, leading=15,
            textColor=colors.HexColor("#333333"),
            leftIndent=16, rightIndent=0,
            spaceAfter=10, spaceBefore=4,
            italic=1,
        ),
        "bullet": S(
            "Bullet",
            fontName=FONT, fontSize=10, leading=15,
            leftIndent=18, bulletIndent=6,
            alignment=TA_LEFT, spaceAfter=4,
        ),
        "code": S(
            "Code",
            fontName="Courier", fontSize=8, leading=11,
            leftIndent=14, rightIndent=6,
            backColor=colors.HexColor("#f5f5f5"),
            spaceAfter=10, spaceBefore=4,
        ),
        # ── 표 ──
        "th": S(
            "TH",
            fontName=FONT_BOLD, fontSize=9, leading=13,
            textColor=colors.white, alignment=TA_LEFT,
        ),
        "td": S(
            "TD",
            fontName=FONT, fontSize=8.5, leading=13,
            alignment=TA_LEFT,
        ),
    }


ST: Dict[str, ParagraphStyle] = {}


# ── 커스텀 DocTemplate ───────────────────────────────────────────

class BPEDoc(BaseDocTemplate):
    def __init__(self, filename: str, **kw: Any) -> None:
        super().__init__(filename, **kw)


# ── 페이지 배경/헤더/푸터 콜백 ──────────────────────────────────

def _draw_cover(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    # 전체 다크 배경
    canvas.setFillColor(C_DARK)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # 하단 포인트 띠
    canvas.setFillColor(C_MID)
    canvas.rect(0, 0, PAGE_W, 2.2 * cm, fill=1, stroke=0)
    # 상단 구분선
    canvas.setStrokeColor(colors.HexColor("#2a6aaa"))
    canvas.setLineWidth(0.8)
    canvas.line(MARGIN_L, PAGE_H - 3.2 * cm, PAGE_W - MARGIN_R, PAGE_H - 3.2 * cm)
    # BELUCA STUDIO 레이블
    canvas.setFont(FONT_BOLD, 8)
    canvas.setFillColor(colors.HexColor("#8aafc8"))
    canvas.drawString(MARGIN_L, PAGE_H - 2.5 * cm, "BELUCA STUDIO  |  내부 배포용")
    canvas.restoreState()


def _draw_normal(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    pn = canvas.getPageNumber() - 1  # 커버를 1로 치면 본문은 2부터 → -1로 오프셋

    # 헤더 라인
    canvas.setStrokeColor(C_LITE)
    canvas.setLineWidth(0.5)
    y_hdr = PAGE_H - MARGIN_T + 5 * mm
    canvas.line(MARGIN_L, y_hdr, PAGE_W - MARGIN_R, y_hdr)
    # 헤더 텍스트
    canvas.setFont(FONT, 7.5)
    canvas.setFillColor(C_GRAY)
    canvas.drawString(MARGIN_L, y_hdr + 1.5 * mm, "BPE 사용자 가이드")
    canvas.drawRightString(PAGE_W - MARGIN_R, y_hdr + 1.5 * mm, "Beluca Pipeline Engine")

    # 푸터 라인
    y_ftr = MARGIN_B - 5 * mm
    canvas.line(MARGIN_L, y_ftr, PAGE_W - MARGIN_R, y_ftr)
    # 푸터 텍스트
    canvas.drawString(MARGIN_L, y_ftr - 3.5 * mm, "사내 배포용  —  무단 외부 배포 금지")
    canvas.drawRightString(PAGE_W - MARGIN_R, y_ftr - 3.5 * mm, f"— {pn} —")

    canvas.restoreState()


# ── Markdown → Flowable 파서 ─────────────────────────────────────

def _table(lines: List[str], start: int) -> Tuple[Any, int]:
    rows_raw: List[List[str]] = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().split("|")[1:-1]]
        rows_raw.append(cells)
        i += 1
    # separator 행 제거
    if len(rows_raw) >= 2:
        sep = rows_raw[1]
        if sep and all(re.match(r"^:?-+:?$", re.sub(r"\s+", "", c)) for c in sep):
            rows_raw = [rows_raw[0]] + rows_raw[2:]

    data: List[List[Paragraph]] = []
    for ri, row in enumerate(rows_raw):
        sty = ST["th"] if ri == 0 else ST["td"]
        data.append([Paragraph(_inline(c), sty) for c in row])

    if not data:
        return Spacer(1, 1), i

    body_w = PAGE_W - MARGIN_L - MARGIN_R
    n_cols = len(data[0])
    col_w = [body_w / max(n_cols, 1)] * n_cols
    tbl = Table(data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(
        TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  C_MID),
            ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
            ("ALIGN",          (0, 0), (-1, -1), "LEFT"),
            ("VALIGN",         (0, 0), (-1, -1), "TOP"),
            ("GRID",           (0, 0), (-1, -1), 0.4, colors.HexColor("#c8d8e8")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_ROW]),
            ("LEFTPADDING",    (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 8),
            ("TOPPADDING",     (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
        ])
    )
    return tbl, i


def _code_block(lines: List[str], start: int) -> Tuple[List[Any], int]:
    i = start + 1
    buf: List[str] = []
    while i < len(lines) and not lines[i].strip().startswith("```"):
        buf.append(lines[i])
        i += 1
    if i < len(lines):
        i += 1
    text = "\n".join(buf)
    p = Paragraph(_esc(text).replace("\n", "<br/>"), ST["code"])
    return [p], i


def _bullets(lines: List[str], start: int) -> Tuple[List[Any], int]:
    out: List[Any] = []
    i = start
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("- "):
            out.append(Paragraph(_inline(s[2:]), ST["bullet"], bulletText="•"))
            i += 1
        else:
            break
    return out, i


SKIP_H2_TITLES = {"목차"}  # 마크다운에 있는 수동 목차 섹션 건너뜀


def md_to_flowables(md_text: str) -> List[Any]:
    lines = md_text.splitlines()
    flow: List[Any] = []
    i = 0
    first_h2 = True  # 첫 H2 앞에는 PageBreak 삽입하지 않음
    skip_until_next_h2 = False  # 건너뛸 섹션 플래그

    while i < len(lines):
        s = lines[i].rstrip()
        stripped = s.strip()

        # 빈 줄 / 구분선 무시
        if not stripped or stripped == "---":
            i += 1
            continue

        # H1 — 커버에서 처리, 본문에서는 건너뜀
        if re.match(r"^# [^#]", s):
            i += 1
            continue

        # H2 — 섹션마다 새 페이지
        if re.match(r"^## [^#]", s):
            h2_title = s[3:].strip()
            if h2_title in SKIP_H2_TITLES:
                # 이 H2와 다음 H2 전까지의 내용 전부 건너뜀
                skip_until_next_h2 = True
                i += 1
                continue
            skip_until_next_h2 = False
            if not first_h2:
                flow.append(PageBreak())
            first_h2 = False
            flow.append(Paragraph(_inline(h2_title), ST["h2"]))
            i += 1
            continue

        # 건너뛸 섹션이면 다음 H2 전까지 스킵
        if skip_until_next_h2:
            i += 1
            continue

        # H3 — 헤딩과 바로 다음 단락을 묶어서 고아 방지
        if re.match(r"^### ", s):
            h3_para = Paragraph(_inline(s[4:].strip()), ST["h3"])
            # 다음 내용 미리 읽어서 KeepTogether
            peek: List[Any] = [h3_para]
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            # 다음 줄이 일반 단락이면 같이 묶음
            if j < len(lines) and not re.match(r"^#{1,3} ", lines[j]):
                nxt = lines[j].strip()
                if nxt and not nxt.startswith("- ") and not nxt.startswith("|"):
                    peek.append(Paragraph(_inline(nxt), ST["body"]))
                    i = j + 1
                    flow.append(KeepTogether(peek))
                    continue
            flow.append(KeepTogether(peek))
            i += 1
            continue

        # 코드 블록
        if stripped.startswith("```"):
            block, i = _code_block(lines, i)
            flow.extend(block)
            flow.append(Spacer(1, 6))
            continue

        # 표
        if stripped.startswith("|"):
            tbl, i = _table(lines, i)
            flow.append(tbl)
            flow.append(Spacer(1, 10))
            continue

        # 불릿 목록
        if stripped.startswith("- "):
            blist, i = _bullets(lines, i)
            flow.extend(blist)
            flow.append(Spacer(1, 6))
            continue

        # 인용 (> ...) — 박스 없이 이탤릭 들여쓰기만
        if stripped.startswith("> "):
            inner = stripped[2:].strip()
            flow.append(Paragraph(_inline(inner), ST["quote"]))
            i += 1
            continue

        # *이탤릭*
        if re.match(r"^\*[^*].+[^*]\*$", stripped):
            flow.append(
                Paragraph("<i>" + _esc(stripped[1:-1]) + "</i>", ST["body"])
            )
            i += 1
            continue

        # 일반 단락 (빈 줄까지 합침)
        buf = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].rstrip()
            ns = nxt.strip()
            if not ns:
                break
            if (
                re.match(r"^#{1,3} ", nxt)
                or ns.startswith("```")
                or ns.startswith("|")
                or ns.startswith("- ")
                or ns.startswith(">")
                or ns == "---"
            ):
                break
            buf.append(ns)
            i += 1
        flow.append(Paragraph(_inline(" ".join(buf)), ST["body"]))

    return flow




# ── 커버 페이지 ──────────────────────────────────────────────────

def cover_page() -> List[Any]:
    flow: List[Any] = []
    flow.append(Spacer(1, 6 * cm))

    flow.append(Paragraph("BPE", ST["cover_title"]))
    flow.append(Paragraph("Beluca Pipeline Engine 사용자 가이드", ST["cover_sub"]))
    flow.append(Spacer(1, 0.8 * cm))

    # 베타 안내 배지
    badge_data = [[Paragraph("⚠  현재 베타 버전입니다", ST["cover_badge"])]]
    badge = Table(badge_data, colWidths=[11 * cm])
    badge.setStyle(
        TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#f5c400")),
            ("LEFTPADDING",   (0, 0), (-1, -1), 12),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ])
    )
    flow.append(badge)
    flow.append(Spacer(1, 0.5 * cm))
    flow.append(
        Paragraph(
            "기능이 지속적으로 추가·개선될 예정입니다.",
            ST["cover_desc"],
        )
    )
    flow.append(
        Paragraph(
            "현재는 My Tasks 편의 기능 위주로 활용해 주세요.",
            ST["cover_desc"],
        )
    )
    flow.append(Spacer(1, 1.2 * cm))
    flow.append(Paragraph("v0.8 Beta  |  2026  |  Beluca Studio", ST["cover_version"]))

    # ★ 반드시 PageBreak 전에 NextPageTemplate 삽입
    flow.append(NextPageTemplate("Normal"))
    flow.append(PageBreak())
    return flow


# ── 빌드 진입점 ──────────────────────────────────────────────────

def convert() -> None:
    print("BPE 가이드 PDF 생성 시작")
    register_fonts()

    global ST
    ST = make_styles()

    print(f"  Markdown 읽는 중: {MD_FILE}")
    with open(MD_FILE, encoding="utf-8") as f:
        md_text = f.read()

    body_flow = md_to_flowables(md_text)

    # ── 프레임 / 템플릿 ──────────────────────────────────────────
    cover_frame = Frame(
        MARGIN_L, MARGIN_B,
        PAGE_W - MARGIN_L - MARGIN_R,
        PAGE_H - MARGIN_T - MARGIN_B,
        id="cover",
    )
    body_frame = Frame(
        MARGIN_L,
        MARGIN_B + FOOTER_H,
        PAGE_W - MARGIN_L - MARGIN_R,
        PAGE_H - MARGIN_T - MARGIN_B - HEADER_H - FOOTER_H,
        id="body",
    )

    cover_tpl  = PageTemplate(id="Cover",  frames=[cover_frame], onPage=_draw_cover)
    normal_tpl = PageTemplate(id="Normal", frames=[body_frame],  onPage=_draw_normal)

    doc = BPEDoc(
        PDF_FILE,
        pagesize=A4,
        title="BPE 사용자 가이드",
        author="Beluca Studio",
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=MARGIN_T,
        bottomMargin=MARGIN_B,
    )
    doc.addPageTemplates([cover_tpl, normal_tpl])

    story: List[Any] = []
    story.extend(cover_page())   # 마지막에 NextPageTemplate("Normal") + PageBreak 포함
    story.extend(body_flow)      # 본문 (2페이지부터 바로 시작)

    print(f"  PDF 생성 중: {PDF_FILE}")
    doc.multiBuild(story)

    size = os.path.getsize(PDF_FILE)
    print(f"\n완료: {PDF_FILE}")
    print(f"크기: {size // 1024} KB")


if __name__ == "__main__":
    convert()
