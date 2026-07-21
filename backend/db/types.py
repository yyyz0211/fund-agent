"""PostgreSQL 专用的 SQLAlchemy 兼容类型。"""
from __future__ import annotations

import json

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator


class JsonText(TypeDecorator):
    """将 JSON 存储为 JSONB，同时保持服务层字符串的约定。
    # 现有服务有意交换 JSON 文本。PostgreSQL 存储已解析的
    # JSONB 值用于索引；此适配器在 ORM 边界执行转换
    # 因此调用者无需特定于方言的分支。
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
