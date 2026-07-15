"""PostgreSQL-specific SQLAlchemy compatibility types."""
from __future__ import annotations

import json

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator


class JsonText(TypeDecorator):
    """Store JSON as JSONB while preserving the service-layer string contract.

    Existing services intentionally exchange JSON text. PostgreSQL stores parsed
    JSONB values for indexing; this adapter performs the conversion at the ORM
    boundary so callers do not need dialect-specific branches.
    """

    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value

    def process_result_value(self, value, dialect):
        if value is None or isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)
