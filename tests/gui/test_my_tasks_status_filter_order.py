"""My Tasks status filter bar order matches Beluca ShotGrid preset codes."""

from __future__ import annotations

from bpe.gui import theme
from bpe.gui.tabs import my_tasks_tab
from bpe.shotgrid.tasks import BELUCA_TASK_STATUS_PRESETS

# ShotGrid 에 cgi 가 추가되기 전 19개 — 이름·순서·라벨이 바뀌면 안 된다
_LEGACY_19 = [
    ("wtg", "Waiting to Start"),
    ("assign", "Assign"),
    ("wip", "work in process"),
    ("retake", "retake"),
    ("cfrm", "SV Confirmed"),
    ("tm", "team confirm"),
    ("sv", "supervisor confirm"),
    ("pub-s", "pulish sent"),
    ("pubok", "publish ok"),
    ("ct", "client confirm"),
    ("cts", "client confirm sent"),
    ("ctr", "client retake"),
    ("cto", "Client confirm ok"),
    ("disent", "DI sent"),
    ("fin", "Final"),
    ("hld", "Hold"),
    ("nocg", "nocg"),
    ("omt", "Omit"),
    ("error", "Error"),
]


def test_status_order_matches_beluca_presets() -> None:
    expected = [code for code, _ in BELUCA_TASK_STATUS_PRESETS]
    assert my_tasks_tab._STATUS_ORDER == expected


def test_beluca_preset_codes_unique() -> None:
    codes = [code for code, _ in BELUCA_TASK_STATUS_PRESETS]
    assert len(codes) == len(set(codes))


def test_cgi_status_in_presets() -> None:
    assert ("cgi", "CGI Confirm") in BELUCA_TASK_STATUS_PRESETS


def test_legacy_presets_unchanged() -> None:
    assert BELUCA_TASK_STATUS_PRESETS[: len(_LEGACY_19)] == _LEGACY_19


def test_every_preset_status_has_badge_color() -> None:
    missing = [c for c, _ in BELUCA_TASK_STATUS_PRESETS if c not in theme.TASK_STATUS_COLORS]
    assert missing == []
