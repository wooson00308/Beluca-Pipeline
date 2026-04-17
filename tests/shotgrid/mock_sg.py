"""Lightweight MockShotgun for unit tests — no network required."""

from __future__ import annotations

import copy
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional


class MockShotgun:
    """In-memory fake of the shotgun_api3.Shotgun client."""

    def __init__(self) -> None:
        self._entities: Dict[str, List[Dict[str, Any]]] = {}
        self._next_id = 1
        self._schema: Dict[str, Dict[str, Any]] = {}
        # config stub
        self.config = _ConfigStub()

    # ── test helpers ─────────────────────────────────────────────────

    def _add_entity(self, entity_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert an entity directly (for test setup)."""
        record = {"type": entity_type, **copy.deepcopy(data)}
        if "id" not in record:
            record["id"] = self._next_id
            self._next_id += 1
        self._entities.setdefault(entity_type, []).append(record)
        return record

    def _set_schema(self, entity_type: str, field_name: str, schema: Dict[str, Any]) -> None:
        self._schema.setdefault(entity_type, {})[field_name] = schema

    # ── SG API surface ───────────────────────────────────────────────

    def find(
        self,
        entity_type: str,
        filters: Any,
        fields: Any,
        *,
        order: Any = None,
        limit: int = 0,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        page = int(kwargs.pop("page", 0) or 0)
        offset = int(kwargs.pop("offset", 0) or 0)
        if page > 0 and limit > 0:
            offset = (page - 1) * limit
        pool = self._entities.get(entity_type, [])
        matched = [e for e in pool if _match_filters(e, filters)]
        if order and isinstance(order, list) and order:
            o0 = order[0]
            if isinstance(o0, dict):
                fn = str(o0.get("field_name") or "id")
                rev = str(o0.get("direction", "asc")).lower() == "desc"

                def _sort_key(ent: Dict[str, Any]) -> Any:
                    v = ent.get(fn)
                    return v if v is not None else 0

                matched = sorted(matched, key=_sort_key, reverse=rev)
        if offset > 0:
            matched = matched[offset:]
        if limit > 0:
            matched = matched[:limit]
        return [_project_fields(e, fields) for e in matched]

    def find_one(
        self,
        entity_type: str,
        filters: Any,
        fields: Any,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        results = self.find(entity_type, filters, fields, limit=1, **kwargs)
        return results[0] if results else None

    def summarize(
        self,
        entity_type: str,
        filters: Any,
        *,
        summary_fields: Any = None,
        grouping: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        pool = self._entities.get(entity_type, [])
        matched = [e for e in pool if _match_filters(e, filters)]
        group_field = "sg_status_list"
        if grouping and isinstance(grouping, list) and grouping:
            g0 = grouping[0]
            if isinstance(g0, dict) and g0.get("field"):
                group_field = str(g0["field"])
        counts: Dict[str, int] = defaultdict(int)
        for e in matched:
            gv = e.get(group_field)
            if isinstance(gv, dict):
                key = str(gv.get("name") or gv.get("code") or gv.get("value") or "").strip().lower()
            else:
                key = str(gv or "").strip().lower()
            if not key:
                key = "(empty)"
            counts[key] += 1
        groups: List[Dict[str, Any]] = []
        for k, v in sorted(counts.items()):
            groups.append({"group_value": k, "summaries": {"id": int(v)}})
        total = len(matched)
        return {"summaries": {"id": total}, "groups": groups}

    def create(self, entity_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        record = {"type": entity_type, "id": self._next_id, **copy.deepcopy(data)}
        self._next_id += 1
        self._entities.setdefault(entity_type, []).append(record)
        return {"type": entity_type, "id": record["id"]}

    def update(self, entity_type: str, entity_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        for e in self._entities.get(entity_type, []):
            if e.get("id") == entity_id:
                e.update(data)
                return {"type": entity_type, "id": entity_id, **data}
        return {"type": entity_type, "id": entity_id}

    def upload(
        self,
        entity_type: str,
        entity_id: int,
        path: str,
        field_name: str = "sg_uploaded_movie",
        **kwargs: Any,
    ) -> int:
        # Mark the entity as having the upload
        for e in self._entities.get(entity_type, []):
            if e.get("id") == entity_id:
                e[field_name] = {"name": path, "url": f"https://fake/{path}"}
                break
        return self._next_id  # fake attachment id

    def upload_thumbnail(
        self,
        entity_type: str,
        entity_id: int,
        path: str,
    ) -> int:
        for e in self._entities.get(entity_type, []):
            if e.get("id") == entity_id:
                e["image"] = {"name": path}
                break
        return self._next_id

    def schema_field_read(
        self,
        entity_type: str,
        field_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        et_schema = self._schema.get(entity_type, {})
        if field_name:
            return et_schema.get(field_name, {})
        return et_schema


class _ConfigStub:
    """Mimics Shotgun().config for timeout_secs."""

    timeout_secs: float = 720.0


# ── filter matching ──────────────────────────────────────────────────


def _match_filters(entity: Dict[str, Any], filters: Any) -> bool:
    """Simplified filter matching — enough for unit tests."""
    if not filters:
        return True
    for f in filters:
        if isinstance(f, dict) and f.get("filter_operator") == "any":
            subfilters = f.get("filters") or []
            ok_any = False
            for sf in subfilters:
                if isinstance(sf, (list, tuple)) and len(sf) >= 3:
                    if _match_single_clause(entity, sf[0], sf[1], sf[2]):
                        ok_any = True
                        break
            if not ok_any:
                return False
            continue
        if not isinstance(f, (list, tuple)) or len(f) < 3:
            continue
        field, op, value = f[0], f[1], f[2]
        if not _match_single_clause(entity, field, op, value):
            return False
    return True


def _match_single_clause(entity: Dict[str, Any], field: Any, op: Any, value: Any) -> bool:
    ev = entity.get(field)
    op_lower = str(op).lower()
    if op_lower == "is":
        if field == "task_assignees" and isinstance(value, dict) and isinstance(ev, list):
            wt, wid = value.get("type"), value.get("id")
            return any(
                isinstance(x, dict) and x.get("type") == wt and x.get("id") == wid for x in ev
            )
        if field == "attachment_links" and isinstance(value, dict):
            if not isinstance(ev, list):
                return False
            wt, wid = value.get("type"), value.get("id")
            return any(
                isinstance(x, dict) and x.get("type") == wt and x.get("id") == wid for x in ev
            )
        if isinstance(value, dict) and isinstance(ev, dict):
            return ev.get("type") == value.get("type") and ev.get("id") == value.get("id")
        return ev == value
    if op_lower == "in":
        if field == "note_links" and isinstance(ev, list) and isinstance(value, list):
            for req in value:
                if not isinstance(req, dict):
                    continue
                rt, rid = req.get("type"), req.get("id")
                for lk in ev:
                    if isinstance(lk, dict) and lk.get("type") == rt and lk.get("id") == rid:
                        return True
            return False
        if field == "task_assignees" and isinstance(ev, list) and isinstance(value, list):
            want_ids = set()
            for req in value:
                if not isinstance(req, dict):
                    continue
                if (req.get("type") or "").lower() != "humanuser":
                    continue
                rid = req.get("id")
                if rid is None:
                    continue
                try:
                    want_ids.add(int(rid))
                except (TypeError, ValueError):
                    continue
            for x in ev:
                if not isinstance(x, dict):
                    continue
                if (x.get("type") or "").lower() != "humanuser":
                    continue
                xid = x.get("id")
                if xid is None:
                    continue
                try:
                    if int(xid) in want_ids:
                        return True
                except (TypeError, ValueError):
                    continue
            return False
        if isinstance(value, list):
            return ev in value
        return False
    if op_lower == "contains":
        if isinstance(ev, str) and isinstance(value, str):
            return value.lower() in ev.lower()
        if isinstance(ev, list):
            return value in ev
        return False
    if op_lower == "starts_with":
        if isinstance(ev, str) and isinstance(value, str):
            return ev.lower().startswith(value.lower())
        return False
    if op_lower == "type_is":
        if isinstance(ev, dict):
            return (ev.get("type") or "").lower() == str(value).lower()
        return False
    if op_lower == "greater_than":
        return bool(_cmp_dt_ok(ev, value, "gt"))
    if op_lower == "less_than":
        return bool(_cmp_dt_ok(ev, value, "lt"))
    return False


def _cmp_dt_ok(ev: Any, value: Any, mode: str) -> bool:
    """Compare datetimes or date strings for greater_than / less_than filters."""
    if ev is None or value is None:
        return False
    a = _to_ts(ev)
    b = _to_ts(value)
    if a is None or b is None:
        return False
    if mode == "gt":
        return a > b
    if mode == "lt":
        return a < b
    return False


def _to_ts(v: Any) -> Optional[float]:
    if isinstance(v, datetime):
        return v.timestamp()
    if isinstance(v, date) and not isinstance(v, datetime):
        from datetime import time as dtime

        return datetime.combine(v, dtime.min).timestamp()
    if isinstance(v, str):
        s = v.strip()
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            try:
                y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
                return datetime(y, m, d).timestamp()
            except ValueError:
                return None
    return None


def _project_fields(entity: Dict[str, Any], fields: Any) -> Dict[str, Any]:
    """Return only requested fields (plus type/id)."""
    if not fields:
        return copy.deepcopy(entity)
    out: Dict[str, Any] = {"type": entity.get("type"), "id": entity.get("id")}
    for f in fields:
        if f in entity:
            out[f] = copy.deepcopy(entity[f])
    return out
