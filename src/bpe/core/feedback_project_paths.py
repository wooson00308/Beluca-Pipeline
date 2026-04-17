"""Feedback / 로컬 경로 탐색용 프로젝트 식별 문자열 (GUI 의존 없음)."""

from __future__ import annotations

from typing import Any, Dict


def effective_project_for_paths(task: Dict[str, Any]) -> str:
    """SG Project.code가 비어 있을 때 로컬 vfx/project_연도/<폴더명> 탐색용 문자열."""
    code = (task.get("project_code") or "").strip()
    folder = (task.get("project_folder") or "").strip()
    name = (task.get("project_name") or "").strip()
    return code or folder or name
