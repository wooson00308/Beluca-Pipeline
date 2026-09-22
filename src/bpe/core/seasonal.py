"""시즌 이벤트(추석) 장식 — 표시 기간 판단, 인사말, 도트 그림 데이터.

GUI 없이 표준 라이브러리만 사용한다. 화면 쪽은 ``bpe.gui.widgets.seasonal_mascot``.

추석이 지나면 날짜 판단만으로 장식이 저절로 사라진다. 흔적까지 지우려면 이 파일,
``gui/widgets/seasonal_mascot.py``, ``tests/core/test_seasonal.py`` 를 지우고
``my_tasks_tab.py`` 의 ``add_chuseok_mascot`` 호출 한 줄을 빼면 된다.
설정 파일(settings.json)에는 아무것도 저장하지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, Tuple

# 표시 기간(양 끝 포함). 9/27 0시가 되면 사라진다.
CHUSEOK_START = date(2026, 9, 22)
CHUSEOK_END = date(2026, 9, 26)

# 클릭할 때마다 순서대로 보여줄 인사말 (끝나면 처음으로)
CHUSEOK_GREETINGS: Tuple[str, ...] = (
    "즐거운 추석 보내세요!",
    "풍성한 한가위 보내세요",
    "보름달처럼 넉넉한 한가위 보내세요",
    "보름달 보며 소원 하나 빌어 봐요",
    "더도 말고 덜도 말고, 늘 한가위만 같기를!",
    "소중한 사람들과 따뜻한 연휴 보내세요",
    "송편은 깨? 콩? 뭐 좋아하세요?",
    "오늘 밤엔 달 한번 올려다봐요",
    "맛있는 거 많이 드시고 푹 쉬세요",
    "귀성길 조심히 다녀오세요",
    "환한 보름달처럼 밝은 한가위 보내세요",
    "연휴 전 마감, 조금만 더 힘내요!",
    "연휴 잘 쉬고 건강하게 만나요",
)

# 말풍선 색 (시즌 전용)
BUBBLE_BG = "#FFF7E0"
BUBBLE_BORDER = "#D9B24A"
BUBBLE_TEXT = "#5a3a10"

# 떡방아 한 번 클릭의 프레임 순서: (시작 ms, 프레임 이름)
POUND_SEQUENCE: Tuple[Tuple[int, str], ...] = (
    (0, "mid"),
    (70, "down"),
    (230, "mid"),
    (300, "up"),
    (420, "mid"),
    (490, "down"),
    (650, "mid"),
    (720, "up"),
)


def is_chuseok_active(today: date) -> bool:
    """오늘 추석 장식을 보여줄지 여부."""
    return CHUSEOK_START <= today <= CHUSEOK_END


def ms_until_next_midnight(now: datetime) -> int:
    """다음 자정까지 남은 밀리초 (최소 1)."""
    nxt = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return max(1, int((nxt - now).total_seconds() * 1000))


def next_index(index: int, count: int) -> int:
    """순서대로 돌아가는 다음 번호."""
    return (index + 1) % count if count > 0 else 0


CHUSEOK_PALETTE: Dict[str, str] = {
    "B": "#8A5A3B",
    "G": "#8DB870",
    "H": "#B9DA9E",
    "K": "#2a1d10",
    "L": "#4E8B3A",
    "O": "#F07A1A",
    "P": "#F2A0B8",
    "Q": "#FDD6E1",
    "R": "#F4A7BD",
    "S": "#F6F1E6",
    "T": "#F4EEDD",
    "W": "#FFFFFF",
    "Y": "#F0CF6A",
    "b": "#5E3B22",
    "e": "#BF9536",
    "g": "#5F8C47",
    "h": "#FAE7A0",
    "n": "#3a2a18",
    "o": "#B8560C",
    "q": "#FFB870",
    "r": "#D97F9C",
    "s": "#CFC5B3",
    "w": "#CFCAD6",
    "y": "#D9B24A",
}

# 도트 그림: 한 글자 = 1픽셀, '.' = 투명. 30x22 장면 3장 + 6x4 송편 조각 3개
CHUSEOK_SPRITES: Dict[str, Tuple[str, ...]] = {
    "up": (
        "..............................",
        ".......yyyyyy.................",
        ".....yyyYYYYyyy...............",
        "....yyYYYYYYYYyy..............",
        "...yYYYYYYYYYYYYeb............",
        "..yyYhYYYYYYYYYYeb............",
        "..yYYWyyYWYYYYYYYb............",
        ".yyYWPWYWPWYYYYYWbe...........",
        ".yYYWPWYWPWYYYYYWbe...........",
        ".yYYWPWYWPWYYYYWwBB...........",
        ".yYYWWWWWWWYYYYWbbb...........",
        ".yYWWWWWWWWWYYWwYYe...........",
        ".yyWWKWWWKWWYyWYYee...........",
        "..yWWWWPWWWWWWwYye............",
        "..ywWWWWWWWWWWYyee............",
        "...ywWWWWWWwYwyyTTTT..........",
        "....eWWWWWWWWyBBBBBBBB........",
        "....WWWWWWWWWeBbbbbbbB...nL...",
        "...WWWWWWWWWw..BBBBBB...OOOO..",
        "...wWWWWWWWw...BBBBBB...OOqO..",
        "....ww..ww......BBBB....OOOO..",
        "...............BBBBBB....oo...",
    ),
    "mid": (
        "..............................",
        ".......yyyyyy.................",
        ".....yyyYYYYyyy...............",
        "....yyYYYYYYYYyy..............",
        "...yYYYYYYYYYYYYe.............",
        "..yyYhYYYYYYYYYYee............",
        "..yYYWyyYWYYYYYYYb............",
        ".yyYWPWYWPWYYYYYYbe...........",
        ".yYYWPWYWPWYYYYYYbe...........",
        ".yYYWPWYWPWYYYYYWbe...........",
        ".yYYWWWWWWWYYYYWWbe...........",
        ".yYWWWWWWWWWYYYWBBB...........",
        ".yyWWKWWWKWWYyWwbbb...........",
        "..yWWWWPWWWWWyWYye............",
        "..ywWWWWWWWWWWwyee............",
        "...ywWWWWWWwYwyyTTTT..........",
        "....eWWWWWWWWyBBBBBBBB........",
        "....WWWWWWWWWeBbbbbbbB...nL...",
        "...WWWWWWWWWw..BBBBBB...OOOO..",
        "...wWWWWWWWw...BBBBBB...OOqO..",
        "....ww..ww......BBBB....OOOO..",
        "...............BBBBBB....oo...",
    ),
    "down": (
        "..............................",
        ".......yyyyyy.................",
        ".....yyyYYYYyyy...............",
        "....yyYYYYYYYYyy..............",
        "...yYYYYYYYYYYYYe.............",
        "..yyYhYYYYYYYYYYee............",
        "..yYYWyyYWYYYYYYYe............",
        ".yyYWPWYWPWYYYYYYee...........",
        ".yYYWPWYWPWYYYYYYbe...........",
        ".yYYWPWYWPWYYYYYYbe...........",
        ".yYYWWWWWWWYYYYYYbe...........",
        ".yYWWWWWWWWWYYYYWbe...........",
        ".yyWWKWWWKWWYyyWWbe...........",
        "..yWWWWPWWWWWyWwBBB...........",
        "..ywWWWWWWWWWWTybbb..T........",
        "...ywWWWWWWwYwyTTTTTT.........",
        "....eWWWWWWWWyBBBBBBBB........",
        "....WWWWWWWWWeBbbbbbbB...nL...",
        "...WWWWWWWWWw..BBBBBB...OOOO..",
        "...wWWWWWWWw...BBBBBB...OOqO..",
        "....ww..ww......BBBB....OOOO..",
        "...............BBBBBB....oo...",
    ),
    "pt_pink": (
        "..QQQ.",
        ".QRRRr",
        "QRRRRr",
        ".rrrr.",
    ),
    "pt_white": (
        "..WWW.",
        ".WSSSs",
        "WSSSSs",
        ".ssss.",
    ),
    "pt_green": (
        "..HHH.",
        ".HGGGg",
        "HGGGGg",
        ".gggg.",
    ),
}
