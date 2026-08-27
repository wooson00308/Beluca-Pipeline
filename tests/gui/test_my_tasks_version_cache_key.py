"""My Tasks 버전 캐시 키 회귀 — 같은 샷의 파트별 카드가 슬롯을 공유하면 안 된다."""

from __future__ import annotations

from bpe.gui.tabs import my_tasks_tab


def _task(shot: str, proj: str, task_content: str) -> dict:
    return {"shot_code": shot, "project_code": proj, "task_content": task_content}


def test_same_shot_different_task_gets_different_key() -> None:
    """comp/rnd 카드가 같은 키를 쓰면 나중 값이 앞 값을 덮어쓴다."""
    comp = my_tasks_tab._version_cache_key(_task("ep06_s043_0010", "SBS_030", "comp"))
    rnd = my_tasks_tab._version_cache_key(_task("ep06_s043_0010", "SBS_030", "rnd"))

    assert comp != rnd


def test_comp_aliases_share_one_key() -> None:
    """폴더가 같으면(comp 별칭·빈 값) 키도 같아야 캐시가 헛돌지 않는다."""
    base = my_tasks_tab._version_cache_key(_task("ep06_s043_0010", "SBS_030", "comp"))

    assert my_tasks_tab._version_cache_key(_task("ep06_s043_0010", "SBS_030", "")) == base
    assert my_tasks_tab._version_cache_key(_task("ep06_s043_0010", "SBS_030", "Comp")) == base


def test_shot_and_project_still_separate_keys() -> None:
    """파트를 넣어도 샷·프로젝트 구분은 그대로 살아 있어야 한다."""
    a = my_tasks_tab._version_cache_key(_task("ep06_s043_0010", "SBS_030", "comp"))
    b = my_tasks_tab._version_cache_key(_task("ep06_s043_0020", "SBS_030", "comp"))
    c = my_tasks_tab._version_cache_key(_task("ep06_s043_0010", "CRS2_032", "comp"))

    assert len({a, b, c}) == 3


def test_project_folder_fallback_still_works() -> None:
    """project_code 가 없으면 project_folder 로 폴백하던 동작은 유지."""
    with_code = my_tasks_tab._version_cache_key(
        {"shot_code": "ep06_s043_0010", "project_code": "SBS_030", "task_content": "rnd"}
    )
    with_folder = my_tasks_tab._version_cache_key(
        {"shot_code": "ep06_s043_0010", "project_folder": "SBS_030", "task_content": "rnd"}
    )

    assert with_code == with_folder
