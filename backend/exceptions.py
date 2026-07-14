"""业务异常类定义。

按规格书 4.3 节定义统一异常体系。

七个标准类别:

| 异常                      | 用途                       | HTTP 默认映射 |
|--------------------------|---------------------------|---------------|
| `FundAgentError`         | 基础业务异常                 | 500           |
| `ResourceNotFoundError`  | 资源不存在                  | 404           |
| `InputValidationError`   | 参数验证失败                 | 400/422       |
| `DataSourceError`        | 外部数据源错误               | 502           |
| `DataSourceTimeoutError` | 外部数据源超时               | 504           |
| `DatabaseConflictError`  | 数据库冲突                  | 409/503       |
| `DependencyUnavailableError` | 可选依赖不可用           | 200+warning   |

规范(规格书 4.3):

- 禁止 `except Exception: pass`。允许在进程、线程、外部数据源和降级边界
  捕获宽异常,但必须记录上下文或返回显式降级状态。
- 日志不得包含 API key、数据库密码、完整持仓或未经脱敏的外部响应。
- 跨模块日志统一携带 `job_id`、`fund_code`、`source`、`stage` 等上下文。
"""
from __future__ import annotations

from typing import Any, Final


# ---------------------------------------------------------------------------
# 异常类层级
# ---------------------------------------------------------------------------


class FundAgentError(Exception):
    """基础业务异常。所有领域异常的根。"""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ResourceNotFoundError(FundAgentError):
    """资源不存在(基金代码 / 简报 ID / schema 记录等)。"""


class InputValidationError(FundAgentError):
    """参数验证失败。"""

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.field = field


class DataSourceError(FundAgentError):
    """外部数据源错误(akshare / FRED / CLS / NMPA 等)。"""

    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.source = source


class DataSourceTimeoutError(DataSourceError):
    """外部数据源超时。"""


class DatabaseConflictError(FundAgentError):
    """数据库冲突(如唯一约束违反 / 死锁 / serialization failure)。"""


class DependencyUnavailableError(FundAgentError):
    """可选依赖不可用(embedding 服务 / pgvector / LLM)。"""

    def __init__(
        self,
        message: str,
        *,
        dependency: str | None = None,
        fallback: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.dependency = dependency
        self.fallback = fallback


# ---------------------------------------------------------------------------
# HTTP 状态码映射
# ---------------------------------------------------------------------------


_HTTP_STATUS: Final[dict[type, int]] = {
    ResourceNotFoundError: 404,
    InputValidationError: 422,
    DataSourceTimeoutError: 504,
    DataSourceError: 502,
    DatabaseConflictError: 409,
}


def http_status_for(exc: BaseException) -> int:
    """把业务异常映射到 HTTP 状态码。

    默认 500。`DependencyUnavailableError` 由 caller 决定映射 503 / 200+warning,
    所以这里返回 503 作为最严的兜底,API 层可以在依赖降级场景下覆盖。
    """
    for cls, status in _HTTP_STATUS.items():
        if isinstance(exc, cls):
            return status
    if isinstance(exc, DependencyUnavailableError):
        return 503
    return 500


# ---------------------------------------------------------------------------
# 日志脱敏
# ---------------------------------------------------------------------------

# 匹配 API key 风格字符串:sk-..., ghp_..., key-..., xoxb-..., AKIA..., 等
_API_KEY_PATTERN = (
    r"(sk-[a-zA-Z0-9]{8,})"          # OpenAI / DeepSeek 等
    r"|(ghp_[a-zA-Z0-9]{8,})"        # GitHub PAT
    r"|(xox[baprs]-[a-zA-Z0-9-]{8,})"  # Slack
    r"|(AKIA[A-Z0-9]{12,})"          # AWS access key
    r"|(AIza[a-zA-Z0-9_-]{8,})"      # Google API key
)

# 显式禁止出现在日志 detail 字段里的 key 名
_SENSITIVE_DETAIL_KEYS: Final[frozenset[str]] = frozenset({
    "api_key",
    "apikey",
    "api-key",
    "authorization",
    "auth",
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "private_key",
    "database_url",
    "db_password",
})

# 这些值会被整体替换为 `***`
_SENSITIVE_PATTERN = __import__("re").compile(_API_KEY_PATTERN)


def redact_string(value: str) -> str:
    """从字符串中删除 API key 等敏感凭证。"""
    return _SENSITIVE_PATTERN.sub("***", value)


def redact_dict(payload: Any, *, _depth: int = 0) -> Any:
    """递归清洗 dict / list / tuple:敏感 key 整值替换,字符串内凭证掩码。

    Args:
        payload: 任意 JSON-like 数据。
        _depth: 内部递归计数器,防止恶意深层 payload 触发递归栈溢出。

    Returns:
        与输入结构相同的新对象(不修改原值)。
    """
    if _depth > 6:
        return "<truncated: depth_exceeded>"
    if isinstance(payload, dict):
        cleaned: dict = {}
        for key, value in payload.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_DETAIL_KEYS:
                cleaned[key] = "***"
            else:
                cleaned[key] = redact_dict(value, _depth=_depth + 1)
        return cleaned
    if isinstance(payload, (list, tuple)):
        cleaned_seq = [redact_dict(item, _depth=_depth + 1) for item in payload]
        return type(payload)(cleaned_seq) if isinstance(payload, tuple) else cleaned_seq
    if isinstance(payload, str):
        return redact_string(payload)
    return payload


__all__ = [
    "DatabaseConflictError",
    "DataSourceError",
    "DataSourceTimeoutError",
    "DependencyUnavailableError",
    "FundAgentError",
    "InputValidationError",
    "ResourceNotFoundError",
    "http_status_for",
    "redact_dict",
    "redact_string",
]
