"""ShotGrid Task queries, status presets, and comp-task helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from bpe.core.logging import get_logger

logger = get_logger("shotgrid.tasks")

# Shot entity field for VFX work order (detected once per process from Shot schema)
_VFX_FIELD_CACHE: Optional[str] = None
# Shot entity field for delivery date (detected once per process from Shot schema)
_DELIVERY_FIELD_CACHE: Optional[str] = None


def _detect_shot_vfx_field(sg: Any) -> str:
    """Return Shot API field name for VFX work order, or "" if none."""
    global _VFX_FIELD_CACHE
    if _VFX_FIELD_CACHE is not None:
        return _VFX_FIELD_CACHE
    names: List[str] = []
    try:
        raw = sg.schema_field_read("Shot")
        if isinstance(raw, dict):
            names = list(raw.keys())
    except Exception as e:
        logger.debug("detect_shot_vfx_field schema read failed: %s", e)
    for name in names:
        low = str(name).lower()
        if "vfx" in low and ("work" in low or "order" in low):
            _VFX_FIELD_CACHE = str(name)
            return _VFX_FIELD_CACHE
    _VFX_FIELD_CACHE = ""
    return ""


def _vfx_work_order_from_row(t: Dict[str, Any], vfx_field: str) -> str:
    if not vfx_field:
        return ""
    key = f"entity.Shot.{vfx_field}"
    val: Any = t.get(key)
    if val is None:
        ent = t.get("entity") or {}
        if isinstance(ent, dict):
            val = ent.get(vfx_field)
    if val is None:
        return ""
    if isinstance(val, dict):
        return str(val.get("name") or val.get("value") or "").strip()
    return str(val).strip()


def _detect_shot_delivery_date_field(sg: Any) -> str:
    """Return Shot API field name for delivery date, or "" if none."""
    global _DELIVERY_FIELD_CACHE
    if _DELIVERY_FIELD_CACHE is not None:
        return _DELIVERY_FIELD_CACHE
    names: List[str] = []
    try:
        raw = sg.schema_field_read("Shot")
        if isinstance(raw, dict):
            names = list(raw.keys())
    except Exception as e:
        logger.debug("detect_shot_delivery_date_field schema read failed: %s", e)
    for name in names:
        if str(name) == "sg_delivery_date":
            _DELIVERY_FIELD_CACHE = str(name)
            return _DELIVERY_FIELD_CACHE
    for name in names:
        low = str(name).lower()
        if "delivery" in low and "date" in low:
            _DELIVERY_FIELD_CACHE = str(name)
            return _DELIVERY_FIELD_CACHE
    for name in names:
        low = str(name).lower()
        if "delivery" in low:
            _DELIVERY_FIELD_CACHE = str(name)
            return _DELIVERY_FIELD_CACHE
    _DELIVERY_FIELD_CACHE = ""
    return ""


def _delivery_date_from_row(t: Dict[str, Any], delivery_field: str) -> Any:
    if not delivery_field:
        return None
    key = f"entity.Shot.{delivery_field}"
    val: Any = t.get(key)
    if val is None:
        ent = t.get("entity") or {}
        if isinstance(ent, dict):
            val = ent.get(delivery_field)
    if val is None:
        return None
    if isinstance(val, dict):
        inner = val.get("date") or val.get("name") or val.get("value")
        return inner
    return val


# ── company task status presets (19) ─────────────────────────────────

BELUCA_TASK_STATUS_PRESETS: List[Tuple[str, str]] = [
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


def task_status_preset_combo_labels() -> List[str]:
    return [f"{code} — {label}" for code, label in BELUCA_TASK_STATUS_PRESETS]


def parse_task_status_selection(selection: str) -> Optional[str]:
    s = (selection or "").strip()
    if not s or s == "(비움)":
        return None
    if s.startswith("(스키마에서 목록 없음"):
        return None
    sep = " — "
    if sep in s:
        return s.split(sep, 1)[0].strip() or None
    return s


def merge_task_status_combo_options(schema_values: List[str]) -> List[str]:
    preset_codes = {c for c, _ in BELUCA_TASK_STATUS_PRESETS}
    labels = task_status_preset_combo_labels()
    seen_codes = set(preset_codes)
    out = ["(비움)"] + list(labels)
    for raw in schema_values:
        v = str(raw).strip()
        if not v or v in seen_codes:
            continue
        seen_codes.add(v)
        out.append(v)
    return out


# ── basic Task CRUD ──────────────────────────────────────────────────


def find_tasks_for_shot(sg: Any, shot_id: int) -> List[Dict[str, Any]]:
    return sg.find(
        "Task",
        [["entity", "is", {"type": "Shot", "id": int(shot_id)}]],
        ["id", "content", "sg_status_list", "project"],
        order=[{"field_name": "content", "direction": "asc"}],
    )


def search_tasks_for_shot(
    sg: Any, shot_id: int, query: str, limit: int = 20
) -> List[Dict[str, Any]]:
    """Task autocomplete — tasks under shot_id whose content contains query."""
    filters: list = [["entity", "is", {"type": "Shot", "id": int(shot_id)}]]
    q = (query or "").strip()
    if q:
        filters.append(["content", "contains", q])
    return sg.find(
        "Task",
        filters,
        ["id", "content", "sg_status_list", "project", "entity"],
        order=[{"field_name": "content", "direction": "asc"}],
        limit=limit,
    )


def pick_task_by_content(
    tasks: List[Dict[str, Any]], content_filter: str
) -> Optional[Dict[str, Any]]:
    needle = (content_filter or "").strip().lower()
    if not needle:
        return tasks[0] if tasks else None
    for t in tasks:
        c = (t.get("content") or "").strip().lower()
        if c == needle or needle in c:
            return t
    return tasks[0] if tasks else None


def update_task_status(
    sg: Any,
    task_id: int,
    status_value: str,
    field_name: Optional[str] = None,
) -> Dict[str, Any]:
    status_value = (status_value or "").strip()
    if not status_value:
        return {}
    fn = (field_name or "").strip() or "sg_status_list"
    return sg.update("Task", int(task_id), {fn: status_value})


def detect_task_status_field(sg: Any) -> Optional[str]:
    for candidate in ("sg_status_list", "sg_task_status"):
        try:
            sch = sg.schema_field_read("Task", candidate)
            if sch and isinstance(sch, dict):
                dt = (sch.get("data_type") or "").lower()
                if "status" in dt or sch.get("properties"):
                    return candidate
        except Exception:
            continue
    return None


def list_task_status_values(sg: Any, field_name: Optional[str] = None) -> Tuple[str, List[str]]:
    fn = (field_name or "").strip() or detect_task_status_field(sg) or "sg_status_list"
    sch = sg.schema_field_read("Task", fn)
    if not sch or not isinstance(sch, dict):
        return fn, []
    props = sch.get("properties") or sch.get("data_type_properties") or {}
    if not isinstance(props, dict):
        props = {}
    for key in ("valid_values", "values", "enum_values", "display_values"):
        vals = props.get(key)
        if isinstance(vals, (list, tuple)) and vals:
            return fn, [str(v) for v in vals]
    nested = props.get("status_list") or {}
    if isinstance(nested, dict):
        vals = nested.get("values") or nested.get("valid_values")
        if isinstance(vals, (list, tuple)) and vals:
            return fn, [str(v) for v in vals]
    return fn, []


# ── comp task / assignee helpers ─────────────────────────────────────


def get_comp_task_and_assignee(
    sg: Any, shot_id: int
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return the comp task and its first assignee for a shot."""
    try:
        tasks = sg.find(
            "Task",
            [
                ["entity", "is", {"type": "Shot", "id": int(shot_id)}],
                ["content", "is", "comp"],
            ],
            ["id", "content", "task_assignees"],
            limit=1,
        )
        if not tasks:
            return None, None
        task = tasks[0]
        assignees = task.get("task_assignees") or []
        return task, (assignees[0] if assignees else None)
    except Exception as e:
        logger.debug("get_comp_task_and_assignee failed shot_id=%s: %s", shot_id, e)
        return None, None


def list_comp_tasks_for_assignee(
    sg: Any,
    human_user_id: int,
    *,
    task_content: str = "comp",
    status_filter: Optional[str] = None,
    status_field_name: Optional[str] = None,
    due_date_field: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Comp tasks assigned to *human_user_id* where entity is Shot."""
    uid = int(human_user_id)
    tc_raw = (task_content or "comp").strip()
    status_fn = (
        (status_field_name or "").strip() or detect_task_status_field(sg) or "sg_status_list"
    )
    due_fn_effective = (due_date_field or "").strip() or "due_date"
    st = (status_filter or "").strip()
    st_use = st and st not in ("(전체)", "(비움)", "(all)", "전체")
    order = [{"field_name": "id", "direction": "desc"}]
    lim = int(limit)

    vfx_field = _detect_shot_vfx_field(sg)
    delivery_field = _detect_shot_delivery_date_field(sg)

    def _task_fields_for_due(due_col: str) -> List[str]:
        out = [
            "id",
            "content",
            due_col,
            "entity",
            "project",
            status_fn,
            "entity.Shot.code",
            "entity.Shot.description",
            "entity.Shot.image",
            "project.Project.code",
            "project.Project.name",
        ]
        if vfx_field:
            out.append(f"entity.Shot.{vfx_field}")
        if delivery_field:
            out.append(f"entity.Shot.{delivery_field}")
        return out

    fields: List[str] = _task_fields_for_due(due_fn_effective)

    def _filters(assignee: list, content: Optional[list]) -> List[list]:
        fl: List[list] = [assignee, ["entity", "type_is", "Shot"]]
        if content:
            fl.append(content)
        if st_use:
            fl.append([status_fn, "is", st])
        return fl

    def _find(
        assignee: list, content: Optional[list], field_list: List[str]
    ) -> List[Dict[str, Any]]:
        return sg.find("Task", _filters(assignee, content), field_list, order=order, limit=lim)

    assignee_is: list = ["task_assignees", "is", {"type": "HumanUser", "id": uid}]
    assignee_try = (
        assignee_is,
        ["task_assignees", "in", {"type": "HumanUser", "id": uid}],
        ["task_assignees", "contains", {"type": "HumanUser", "id": uid}],
    )
    content_is: Optional[list] = ["content", "is", tc_raw] if tc_raw else None
    content_has: Optional[list] = ["content", "contains", tc_raw] if tc_raw else None

    rows: List[Dict[str, Any]] = []
    due_read_col = due_fn_effective

    def _find_with_assignee_fallback(content: Optional[list]) -> None:
        nonlocal rows
        try:
            rows = _find(assignee_is, content, fields)
            return
        except Exception as e1:
            el = str(e1).lower()
            if due_fn_effective != "due_date" and due_fn_effective.lower() in el:
                raise
            if "task_assignees" not in el:
                raise
        last_exc: Optional[BaseException] = None
        for af in assignee_try[1:]:
            try:
                rows = _find(af, content, fields)
                return
            except Exception as e2:
                last_exc = e2
                rows = []
        if last_exc is not None:
            raise last_exc

    try:
        rows = _find(assignee_is, content_is, fields)
    except Exception as e1:
        el = str(e1).lower()
        if due_fn_effective != "due_date" and due_fn_effective.lower() in el:
            fields = _task_fields_for_due("due_date")
            due_read_col = "due_date"
            _find_with_assignee_fallback(content_is)
        elif "task_assignees" in el:
            _find_with_assignee_fallback(content_is)
        else:
            raise e1

    if not rows and content_has is not None:
        try:
            rows = _find(assignee_is, content_has, fields)
        except Exception as e1:
            logger.debug("list_comp_tasks_for_assignee content_has primary: %s", e1)
            try:
                _find_with_assignee_fallback(content_has)
            except Exception as e2:
                logger.warning(
                    "list_comp_tasks_for_assignee content_has fallback failed user=%s: %s",
                    uid,
                    e2,
                )
                rows = []

    out: List[Dict[str, Any]] = []
    for t in rows or []:
        ent = t.get("entity") or {}
        if (ent.get("type") or "").lower() != "shot":
            continue
        shot_code = (ent.get("code") or ent.get("name") or "").strip()
        desc = (ent.get("description") or "").strip()
        img = t.get("entity.Shot.image") or ent.get("image")
        proj = t.get("project") or {}
        proj_code = (proj.get("code") or "").strip()
        proj_name = (proj.get("name") or "").strip()
        due_val = t.get(due_read_col)
        folder = (proj_code or proj_name).strip()
        out.append(
            {
                "task_id": t.get("id"),
                "task_content": (t.get("content") or "").strip(),
                "task_status": (t.get(status_fn) or "").strip(),
                "status_field": status_fn,
                "due_date": due_val,
                "delivery_date": _delivery_date_from_row(t, delivery_field),
                "vfx_work_order": _vfx_work_order_from_row(t, vfx_field),
                "shot_id": ent.get("id"),
                "shot_code": shot_code,
                "shot_description": desc,
                "shot_image": img,
                "project_id": proj.get("id"),
                "project_code": proj_code,
                "project_name": proj_name,
                "project_folder": folder,
                "latest_version_code": "",
            }
        )
    return out


def list_comp_tasks_for_project_user(
    sg: Any,
    project_id: int,
    human_user_id: int,
    *,
    task_content: str = "comp",
    status_filter: Optional[str] = None,
    status_field_name: Optional[str] = None,
    due_date_field: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Comp tasks for a specific project + assignee.

    If *project_id* is None, delegates to :func:`list_comp_tasks_for_assignee`.
    """
    if project_id is None:
        return list_comp_tasks_for_assignee(
            sg,
            human_user_id,
            task_content=task_content,
            status_filter=status_filter,
            status_field_name=status_field_name,
            due_date_field=due_date_field,
            limit=limit,
        )

    if status_field_name:
        status_fn = status_field_name.strip()
    else:
        detected = detect_task_status_field(sg)
        status_fn = detected if detected else "sg_status_list"

    st: str = (status_filter or "").strip()
    st_use: bool = bool(st)
    due_fn_effective = (due_date_field or "").strip() or "due_date"

    vfx_field = _detect_shot_vfx_field(sg)
    delivery_field = _detect_shot_delivery_date_field(sg)

    def _fields() -> List[str]:
        base = [
            "id",
            "content",
            status_fn,
            due_fn_effective,
            "project",
            "entity",
            "entity.Shot.code",
            "entity.Shot.description",
            "entity.Shot.image",
            "project.Project.code",
            "project.Project.name",
        ]
        if due_fn_effective != "due_date":
            base.append("due_date")
        if vfx_field:
            base.append(f"entity.Shot.{vfx_field}")
        if delivery_field:
            base.append(f"entity.Shot.{delivery_field}")
        return base

    tc_raw = (task_content or "").strip()
    base_filters: List[Any] = [
        ["project", "is", {"type": "Project", "id": int(project_id)}],
        ["entity", "type_is", "Shot"],
        ["task_assignees", "is", {"type": "HumanUser", "id": int(human_user_id)}],
    ]
    if tc_raw:
        base_filters.append(["content", "contains", tc_raw])
    if st_use:
        base_filters.append([status_fn, "is", st])

    def _fields_with_version() -> List[str]:
        return _fields() + ["sg_latest_version", "sg_latest_version.Version.code"]

    rows: List[Dict[str, Any]] = []
    due_read_col = due_fn_effective
    try:
        rows = sg.find("Task", base_filters, _fields_with_version(), limit=limit)
    except Exception:
        try:
            rows = sg.find("Task", base_filters, _fields(), limit=limit)
        except Exception as e1:
            el = str(e1).lower()
            if due_fn_effective != "due_date" and due_fn_effective.lower() in el:
                due_read_col = "due_date"
                fb_fields = [
                    "id",
                    "content",
                    status_fn,
                    "due_date",
                    "project",
                    "entity",
                    "entity.Shot.code",
                    "entity.Shot.description",
                    "entity.Shot.image",
                    "project.Project.code",
                    "project.Project.name",
                ]
                if vfx_field:
                    fb_fields.append(f"entity.Shot.{vfx_field}")
                if delivery_field:
                    fb_fields.append(f"entity.Shot.{delivery_field}")
                try:
                    rows = sg.find("Task", list(base_filters), fb_fields, limit=limit)
                except Exception as e3:
                    logger.warning(
                        "list_comp_tasks_for_project_user due_date fallback failed: %s", e3
                    )
                    rows = []
            else:
                rows = []

    out: List[Dict[str, Any]] = []
    for t in rows:
        ent = t.get("entity") or {}
        if (ent.get("type") or "").lower() != "shot":
            continue
        proj = t.get("project") or {}
        due_val = t.get(due_read_col)
        proj_code = (proj.get("code") or "").strip()
        proj_name = (proj.get("name") or "").strip()
        ver = t.get("sg_latest_version")
        latest_ver = ""
        if isinstance(ver, dict):
            latest_ver = (ver.get("code") or ver.get("name") or "").strip()
        out.append(
            {
                "task_id": t.get("id"),
                "task_content": (t.get("content") or "").strip(),
                "task_status": (t.get(status_fn) or "").strip(),
                "status_field": status_fn,
                "due_date": due_val,
                "delivery_date": _delivery_date_from_row(t, delivery_field),
                "vfx_work_order": _vfx_work_order_from_row(t, vfx_field),
                "shot_id": ent.get("id"),
                "shot_code": (ent.get("code") or ent.get("name") or "").strip(),
                "shot_description": (ent.get("description") or "").strip(),
                "shot_image": t.get("entity.Shot.image") or ent.get("image"),
                "project_id": proj.get("id"),
                "project_code": proj_code,
                "project_name": proj_name,
                "project_folder": (proj_code or proj_name).strip(),
                "latest_version_code": latest_ver,
            }
        )
    return out
