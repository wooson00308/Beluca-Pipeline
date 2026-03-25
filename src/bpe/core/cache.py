"""Nuke cache read/write — formats, colorspaces, datatypes, OCIO configs."""

from __future__ import annotations

from typing import Any, Dict, List

from bpe.core.atomic_io import read_json_file, write_json_file
import bpe.core.config as cfg


def load_nuke_formats_cache() -> Dict[str, Any]:
    return read_json_file(cfg.FORMAT_CACHE_FILE, default={})


def save_nuke_formats_cache(data: Dict[str, Any]) -> None:
    write_json_file(cfg.FORMAT_CACHE_FILE, data)


def load_colorspaces_cache() -> List[str]:
    return read_json_file(cfg.COLORSPACE_CACHE_FILE, default=[])


def save_colorspaces_cache(data: List[str]) -> None:
    write_json_file(cfg.COLORSPACE_CACHE_FILE, data)


def load_datatypes_cache() -> List[str]:
    return read_json_file(cfg.DATATYPE_CACHE_FILE, default=[])


def save_datatypes_cache(data: List[str]) -> None:
    write_json_file(cfg.DATATYPE_CACHE_FILE, data)


def load_ocio_configs_cache() -> List[str]:
    return read_json_file(cfg.OCIO_CONFIG_CACHE_FILE, default=[])


def save_ocio_configs_cache(data: List[str]) -> None:
    write_json_file(cfg.OCIO_CONFIG_CACHE_FILE, data)
