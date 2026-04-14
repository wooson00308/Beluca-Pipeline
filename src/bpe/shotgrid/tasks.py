"""ShotGrid Task queries, status presets, and comp-task helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from bpe.core.logging import get_logger

logger = get_logger("shotgrid.tasks")

# My Tasks All Tasks: paginated Task.find over project Shot tasks (no single-find cap)
_ALL_TASKS_FIND_CHUNK = 500
# Max Task rows to scan (offset ceiling); log if a full chunk remains at cap
# Very large projects: scan stops here with a warning (avoids unbounded memory/time)
_ALL_TASKS_MAX_SCAN_ROWS = 300_000

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


def list_tasks_for_project_assignee(
    sg: Any,
    project_id: int,
    human_user_id: int,
    *,
    limit: int = 300,
) -> List[Dict[str, Any]]:
    """Tasks on *project_id* assigned to *human_user_id* (any entity type)."""
    uid = int(human_user_id)
    pid = int(project_id)
    fields = ["id", "content", "entity", "project", "sg_status_list", "task_assignees"]
    order = [{"field_name": "content", "direction": "asc"}]
    lim = int(limit)
    base = [["project", "is", {"type": "Project", "id": pid}]]
    assignee_try: List[List[Any]] = [
        ["task_assignees", "is", {"type": "HumanUser", "id": uid}],
        ["task_assignees", "in", {"type": "HumanUser", "id": uid}],
        ["task_assignees", "contains", {"type": "HumanUser", "id": uid}],
    ]
    for af in assignee_try:
        filters = base + [af]
        try:
            rows = sg.find("Task", filters, fields, order=order, limit=lim)
            if rows:
                return list(rows)
        except Exception:
            continue
    return []


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


def _my_tasks_dict_from_task_row(
    t: Dict[str, Any],
    *,
    status_fn: str,
    due_read_col: str,
    delivery_field: str,
    vfx_field: str,
) -> Optional[Dict[str, Any]]:
    """One Task row to My Tasks dict, or None if entity is not a Shot."""
    ent = t.get("entity") or {}
    if (ent.get("type") or "").lower() != "shot":
        return None
    proj = t.get("project") or {}
    due_val = t.get(due_read_col)
    proj_code = (proj.get("code") or "").strip()
    proj_name = (proj.get("name") or "").strip()
    ver = t.get("sg_latest_version")
    latest_ver = ""
    if isinstance(ver, dict):
        latest_ver = (ver.get("code") or ver.get("name") or "").strip()
    return {
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


def _task_has_human_assignees(t: Dict[str, Any]) -> bool:
    """True if Task has at least one HumanUser in ``task_assignees``."""
    raw = t.get("task_assignees")
    if not isinstance(raw, list) or not raw:
        return False
    for x in raw:
        if not isinstance(x, dict):
            continue
        if (str(x.get("type") or "")).lower() != "humanuser":
            continue
        if x.get("id") is not None:
            return True
    return False


def _dedupe_my_tasks_rows_by_shot(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One card per Shot: prefer ``content`` matching *comp*, else highest ``task_id``."""

    def _rep_score(r: Dict[str, Any]) -> Tuple[int, int]:
        c = (r.get("task_content") or "").strip().lower()
        comp = 1 if c == "comp" else (1 if "comp" in c else 0)
        try:
            tid = int(r.get("task_id") or 0)
        except (TypeError, ValueError):
            tid = 0
        return (comp, tid)

    best: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        sid = r.get("shot_id")
        if sid is None:
            continue
        try:
            ik = int(sid)
        except (TypeError, ValueError):
            continue
        cur = best.get(ik)
        if cur is None or _rep_score(r) > _rep_score(cur):
            best[ik] = r
    out = list(best.values())
    out.sort(key=lambda x: int(x.get("task_id") or 0), reverse=True)
    return out


def _project_all_tasks_collect_deduped_rows(
    sg: Any,
    project_id: int,
    *,
    task_content: str = "",
    status_field_name: Optional[str] = None,
    due_date_field: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """Every Shot-linked Task on the project with a HumanUser assignee, deduped by Shot.

    Paginated ``find`` so large projects are not limited to one page of rows. Unassigned
    Tasks are skipped so counts reflect **shots that have someone on a Task** (PM overview).

    Status filtering for the UI is applied after this collect
    (see :func:`load_my_tasks_all_tasks_bundle`).

    Returns ``(my_tasks_dict_rows, status_field_name_used)``.
    """
    pid = int(project_id)

    if status_field_name:
        status_fn = status_field_name.strip()
    else:
        detected = detect_task_status_field(sg)
        status_fn = detected if detected else "sg_status_list"

    due_fn_effective = (due_date_field or "").strip() or "due_date"
    vfx_field = _detect_shot_vfx_field(sg)
    delivery_field = _detect_shot_delivery_date_field(sg)

    def _fields() -> List[str]:
        base = [
            "id",
            "content",
            status_fn,
            due_fn_effective,
            "task_assignees",
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

    def _fields_with_version() -> List[str]:
        return _fields() + ["sg_latest_version", "sg_latest_version.Version.code"]

    tc_raw = (task_content or "").strip()
    base_filters: List[Any] = [
        ["project", "is", {"type": "Project", "id": pid}],
        ["entity", "type_is", "Shot"],
    ]
    if tc_raw:
        base_filters.append(["content", "contains", tc_raw])

    order = [{"field_name": "id", "direction": "desc"}]
    flds_v = _fields_with_version()
    flds_min = _fields()
    due_read_col = due_fn_effective

    fb_fields: List[str] = [
        "id",
        "content",
        status_fn,
        "due_date",
        "task_assignees",
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

    working_fields: Optional[List[str]] = None
    last_exc: Optional[Exception] = None
    for cand in (flds_v, flds_min):
        try:
            sg.find(
                "Task",
                list(base_filters),
                cand,
                order=order,
                limit=_ALL_TASKS_FIND_CHUNK,
                page=1,
            )
            working_fields = cand
            break
        except Exception as exc:
            last_exc = exc
            working_fields = None
    if working_fields is None and due_fn_effective != "due_date":
        due_read_col = "due_date"
        try:
            sg.find(
                "Task",
                list(base_filters),
                fb_fields,
                order=order,
                limit=_ALL_TASKS_FIND_CHUNK,
                page=1,
            )
            working_fields = fb_fields
        except Exception as exc:
            last_exc = exc
            working_fields = None
    if working_fields is None:
        if last_exc is not None:
            logger.warning(
                "_project_all_tasks_collect_deduped_rows: cannot read Tasks: %s",
                last_exc,
            )
        return [], status_fn

    merged: Dict[int, Dict[str, Any]] = {}
    page_num = 1
    total_scanned = 0
    hit_cap = False
    while total_scanned < _ALL_TASKS_MAX_SCAN_ROWS:
        try:
            chunk_rows = list(
                sg.find(
                    "Task",
                    list(base_filters),
                    working_fields,
                    order=order,
                    limit=_ALL_TASKS_FIND_CHUNK,
                    page=page_num,
                )
                or []
            )
        except Exception as exc:
            logger.warning(
                "_project_all_tasks_collect_deduped_rows page=%s: %s",
                page_num,
                exc,
            )
            break
        if not chunk_rows:
            break
        for t in chunk_rows:
            if not _task_has_human_assignees(t):
                continue
            tid = t.get("id")
            if tid is None:
                continue
            try:
                merged[int(tid)] = t
            except (TypeError, ValueError):
                continue
        total_scanned += len(chunk_rows)
        if len(chunk_rows) < _ALL_TASKS_FIND_CHUNK:
            break
        if total_scanned >= _ALL_TASKS_MAX_SCAN_ROWS:
            hit_cap = True
            break
        page_num += 1
    if hit_cap:
        logger.warning(
            "_project_all_tasks_collect_deduped_rows: scan capped at %s Task rows (project=%s)",
            _ALL_TASKS_MAX_SCAN_ROWS,
            pid,
        )

    my_rows: List[Dict[str, Any]] = []
    for _tid, t in sorted(merged.items(), key=lambda kv: -kv[0]):
        row = _my_tasks_dict_from_task_row(
            t,
            status_fn=status_fn,
            due_read_col=due_read_col,
            delivery_field=delivery_field,
            vfx_field=vfx_field,
        )
        if row is not None:
            my_rows.append(row)

    deduped = _dedupe_my_tasks_rows_by_shot(my_rows)
    return deduped, status_fn


def load_my_tasks_all_tasks_bundle(
    sg: Any,
    project_id: int,
    *,
    page_1based: int = 1,
    page_size: int = 100,
    task_content: str = "",
    status_filter_active: Optional[str] = None,
    status_field_name: Optional[str] = None,
    due_date_field: Optional[str] = None,
) -> Dict[str, Any]:
    """Single ShotGrid collect for My Tasks All Tasks: status chips + filtered page.

    *status_filter_active* narrows the **paged list** (and pager ``total``); chip counts use the
    full project Shot set (assigned Tasks only, one representative row per Shot).
    """
    page = max(1, int(page_1based))
    psize = max(1, int(page_size))
    offset = (page - 1) * psize

    rows_full, status_fn = _project_all_tasks_collect_deduped_rows(
        sg,
        int(project_id),
        task_content=task_content,
        status_field_name=status_field_name,
        due_date_field=due_date_field,
    )
    counts: Dict[str, int] = {}
    for r in rows_full:
        code = (r.get("task_status") or "").strip().lower()
        if not code:
            continue
        counts[code] = counts.get(code, 0) + 1
    total_all = len(rows_full)

    st_a = (status_filter_active or "").strip().lower()
    if st_a and st_a != "all":
        page_source = [r for r in rows_full if (r.get("task_status") or "").strip().lower() == st_a]
    else:
        page_source = list(rows_full)
    total_pager = len(page_source)
    page_rows = page_source[offset : offset + psize]
    return {
        "_bpe_bundle": True,
        "tasks": page_rows,
        "status_counts": counts,
        "total": total_pager,
        "total_all": total_all,
        "status_field": status_fn,
    }


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
        row = _my_tasks_dict_from_task_row(
            t,
            status_fn=status_fn,
            due_read_col=due_read_col,
            delivery_field=delivery_field,
            vfx_field=vfx_field,
        )
        if row is not None:
            out.append(row)
    return out


def summarize_shot_tasks_for_project(
    sg: Any,
    project_id: int,
    *,
    task_content: str = "",
    status_field_name: Optional[str] = None,
    due_date_field: Optional[str] = None,
) -> Tuple[Dict[str, int], int]:
    """Count by status for My Tasks All Tasks (assigned Shot Tasks, deduped by Shot)."""
    rows, _ = _project_all_tasks_collect_deduped_rows(
        sg,
        int(project_id),
        task_content=task_content,
        status_field_name=status_field_name,
        due_date_field=due_date_field,
    )
    counts: Dict[str, int] = {}
    for r in rows:
        code = (r.get("task_status") or "").strip().lower()
        if not code:
            continue
        counts[code] = counts.get(code, 0) + 1
    return counts, len(rows)


def list_comp_tasks_for_project_shot_paged(
    sg: Any,
    project_id: int,
    *,
    page_1based: int = 1,
    page_size: int = 100,
    task_content: str = "",
    status_filter: Optional[str] = None,
    status_field_name: Optional[str] = None,
    due_date_field: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """One page of My Tasks All Tasks (same rules as :func:`load_my_tasks_all_tasks_bundle`)."""
    b = load_my_tasks_all_tasks_bundle(
        sg,
        int(project_id),
        page_1based=page_1based,
        page_size=page_size,
        task_content=task_content,
        status_filter_active=status_filter,
        status_field_name=status_field_name,
        due_date_field=due_date_field,
    )
    tasks = b.get("tasks")
    return tasks if isinstance(tasks, list) else []


def list_review_tasks_for_project(
    sg: Any,
    project_id: int,
    *,
    statuses: Optional[List[str]] = None,
    task_content: str = "comp",
    status_field_name: Optional[str] = None,
    due_date_field: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Comp tasks on *project_id* linked to Shots, filtered by task status (e.g. sv, tm).

    No assignee filter — for supervisor / feedback review queues.

    Query order:
    1. ``[status_fn, "in", statuses]`` when multiple statuses.
    2. ``filter_operator: any`` with per-status ``is`` clauses.
    3. Separate ``find`` per status, merged by task id (dedupe).
    """
    if status_field_name:
        status_fn = status_field_name.strip()
    else:
        detected = detect_task_status_field(sg)
        status_fn = detected if detected else "sg_status_list"

    raw_statuses = statuses if statuses is not None else ["sv", "tm"]
    st_list = [str(s).strip().lower() for s in raw_statuses if str(s).strip()]
    if not st_list:
        st_list = ["sv", "tm"]

    due_fn_effective = (due_date_field or "").strip() or "due_date"
    vfx_field = _detect_shot_vfx_field(sg)
    delivery_field = _detect_shot_delivery_date_field(sg)
    tc_raw = (task_content or "").strip()

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

    def _fields_with_version() -> List[str]:
        return _fields() + [
            "sg_latest_version",
            "sg_latest_version.Version.code",
            "sg_latest_version.Version.sg_path_to_movie",
        ]

    base_filters: List[Any] = [
        ["project", "is", {"type": "Project", "id": int(project_id)}],
        ["entity", "type_is", "Shot"],
    ]
    if tc_raw:
        base_filters.append(["content", "contains", tc_raw])

    rows: List[Dict[str, Any]] = []
    due_read_col = due_fn_effective

    def _find_with_fields(field_list: List[str], extra: List[Any]) -> List[Dict[str, Any]]:
        return list(sg.find("Task", base_filters + extra, field_list, limit=int(limit)) or [])

    # 1) "in" list
    try:
        rows = _find_with_fields(_fields_with_version(), [[status_fn, "in", st_list]])
    except Exception as exc:
        logger.debug("list_review_tasks_for_project 'in' filter failed: %s", exc)
        rows = []

    # 2) OR via filter_operator any
    if not rows and len(st_list) > 1:
        any_clause: Dict[str, Any] = {
            "filter_operator": "any",
            "filters": [[status_fn, "is", s] for s in st_list],
        }
        try:
            rows = _find_with_fields(_fields_with_version(), [any_clause])
        except Exception as exc2:
            logger.debug("list_review_tasks_for_project 'any' fallback failed: %s", exc2)
            rows = []

    # 3) Per-status merge
    if not rows:
        seen: Dict[int, Dict[str, Any]] = {}
        for st in st_list:
            try:
                part = _find_with_fields(_fields_with_version(), [[status_fn, "is", st]])
            except Exception as exc3:
                logger.debug("list_review_tasks_for_project per-status find failed: %s", exc3)
                part = []
            for t in part:
                tid = t.get("id")
                if tid is not None:
                    try:
                        seen[int(tid)] = t
                    except (TypeError, ValueError):
                        pass
        rows = list(seen.values())

    # due_date column fallback (match list_comp_tasks_for_project_user)
    if not rows:
        return []

    def _map_rows(task_rows: List[Dict[str, Any]], read_col: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for t in task_rows:
            ent = t.get("entity") or {}
            if (ent.get("type") or "").lower() != "shot":
                continue
            proj = t.get("project") or {}
            due_val = t.get(read_col)
            proj_code = (proj.get("code") or "").strip()
            proj_name = (proj.get("name") or "").strip()
            ver = t.get("sg_latest_version")
            latest_ver = ""
            latest_ver_id: Optional[int] = None
            if isinstance(ver, dict):
                latest_ver = (ver.get("code") or ver.get("name") or "").strip()
                vid = ver.get("id")
                if vid is not None:
                    try:
                        latest_ver_id = int(vid)
                    except (TypeError, ValueError):
                        latest_ver_id = None
            sg_movie_path = t.get("sg_latest_version.Version.sg_path_to_movie")
            latest_sg_path = str(sg_movie_path).strip() if sg_movie_path is not None else ""
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
                    "latest_version_id": latest_ver_id,
                    "latest_version_sg_path": latest_sg_path,
                }
            )
        return out

    return _map_rows(rows, due_read_col)
