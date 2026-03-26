"""BPE 앱 아이콘 생성 스크립트.

Pillow로 브랜드 색상 기반 'B' 로고 아이콘을 생성한다.
  python installer/generate_icon.py

출력:
  installer/icon.png   (1024x1024, 마스터)
  installer/icon.ico   (Windows, 멀티 사이즈)
  installer/icon.icns  (macOS)
"""

from __future__ import annotations

import struct
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _make_master(size: int = 1024) -> Image.Image:
    """1024x1024 마스터 아이콘 이미지를 생성한다."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 배경: 라운드 사각형 (다크)
    bg_color = (28, 28, 30, 255)  # #1c1c1e
    margin = int(size * 0.06)
    radius = int(size * 0.22)
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=radius,
        fill=bg_color,
    )

    # 'B' 글자 (오렌지 #f08a24)
    accent = (240, 138, 36, 255)
    font_size = int(size * 0.55)

    # 시스템 폰트 시도
    font = None
    font_candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for fp in font_candidates:
        try:
            font = ImageFont.truetype(fp, font_size)
            break
        except (OSError, IOError):
            continue

    if font is None:
        font = ImageFont.load_default()

    # 글자 중앙 배치
    bbox = draw.textbbox((0, 0), "B", font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1] + int(size * 0.02)
    draw.text((tx, ty), "B", fill=accent, font=font)

    return img


def _save_ico(master: Image.Image, out: Path) -> None:
    """멀티 사이즈 .ico 저장."""
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [master.resize((s, s), Image.Resampling.LANCZOS) for s in sizes]
    imgs[0].save(str(out), format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[1:])


def _save_icns(master: Image.Image, out: Path) -> None:
    """간단한 .icns 저장 (iconutil 없이 직접 생성)."""
    # icns 포맷: 각 아이콘 타입별 PNG 데이터를 묶는다
    icon_types = [
        (b"icp4", 16),
        (b"icp5", 32),
        (b"icp6", 64),
        (b"ic07", 128),
        (b"ic08", 256),
        (b"ic09", 512),
        (b"ic10", 1024),
    ]

    entries = []
    for tag, size in icon_types:
        resized = master.resize((size, size), Image.Resampling.LANCZOS)
        buf = BytesIO()
        resized.save(buf, format="PNG")
        png_data = buf.getvalue()
        # 각 엔트리: 4바이트 타입 + 4바이트 길이(헤더 포함) + 데이터
        entry_len = 8 + len(png_data)
        entries.append(struct.pack(">4sI", tag, entry_len) + png_data)

    body = b"".join(entries)
    total_len = 8 + len(body)
    header = struct.pack(">4sI", b"icns", total_len)

    out.write_bytes(header + body)


def main() -> None:
    out_dir = Path(__file__).resolve().parent

    print("마스터 아이콘 생성 중...")
    master = _make_master(1024)

    png_path = out_dir / "icon.png"
    master.save(str(png_path), format="PNG")
    print(f"  → {png_path}")

    ico_path = out_dir / "icon.ico"
    _save_ico(master, ico_path)
    print(f"  → {ico_path}")

    icns_path = out_dir / "icon.icns"
    _save_icns(master, icns_path)
    print(f"  → {icns_path}")

    print("완료!")


if __name__ == "__main__":
    main()
