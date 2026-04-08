"""My Tasks status filter bar order matches Beluca ShotGrid preset codes."""

from __future__ import annotations

from bpe.gui.tabs import my_tasks_tab
from bpe.shotgrid.tasks import BELUCA_TASK_STATUS_PRESETS


def test_status_order_matches_beluca_presets() -> None:
    expected = [code for code, _ in BELUCA_TASK_STATUS_PRESETS]
    assert my_tasks_tab._STATUS_ORDER == expected


def test_beluca_preset_codes_unique() -> None:
    codes = [code for code, _ in BELUCA_TASK_STATUS_PRESETS]
    assert len(codes) == len(set(codes))
