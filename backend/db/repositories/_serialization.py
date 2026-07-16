"""Repository 领域共享的私有序列化 helper。"""
from __future__ import annotations


def json_loads(value, fallback):
    import json as _json
    if not value:
        return fallback
    try:
        parsed = _json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed


__all__ = ["json_loads"]
