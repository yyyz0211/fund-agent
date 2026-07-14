"""业务异常类定义。

按规格书 4.3 节定义统一异常体系。
"""
from __future__ import annotations


class FundAgentError(Exception):
    """基础业务异常。"""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ResourceNotFoundError(FundAgentError):
    """资源不存在。"""


class InputValidationError(FundAgentError):
    """参数验证失败。"""


class DataSourceError(FundAgentError):
    """外部数据源错误。"""

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
    """数据库冲突（如唯一约束违反）。"""


class DependencyUnavailableError(FundAgentError):
    """可选依赖不可用（如 embedding 服务）。"""

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
