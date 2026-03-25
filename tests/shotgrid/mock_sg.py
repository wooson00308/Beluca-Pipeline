"""Lightweight MockShotgun for unit tests — no network required."""

from __future__ import annotations

import copy
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
        pool = self._entities.get(entity_type, [])
        matched = [e for e in pool if _match_filters(e, filters)]
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
        if not isinstance(f, (list, tuple)) or len(f) < 3:
            continue
        field, op, value = f[0], f[1], f[2]
        ev = entity.get(field)
        op_lower = str(op).lower()
        if op_lower == "is":
            if isinstance(value, dict) and isinstance(ev, dict):
                if ev.get("type") != value.get("type") or ev.get("id") != value.get("id"):
                    return False
            elif ev != value:
                return False
        elif op_lower == "contains":
            if isinstance(ev, str) and isinstance(value, str):
                if value.lower() not in ev.lower():
                    return False
            elif isinstance(ev, list):
                if value not in ev:
                    return False
            else:
                return False
        elif op_lower == "type_is":
            if isinstance(ev, dict):
                if (ev.get("type") or "").lower() != str(value).lower():
                    return False
            else:
                return False
    return True


def _project_fields(entity: Dict[str, Any], fields: Any) -> Dict[str, Any]:
    """Return only requested fields (plus type/id)."""
    if not fields:
        return copy.deepcopy(entity)
    out: Dict[str, Any] = {"type": entity.get("type"), "id": entity.get("id")}
    for f in fields:
        if f in entity:
            out[f] = copy.deepcopy(entity[f])
    return out
