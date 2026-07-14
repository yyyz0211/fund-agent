"""结构化日志:统一携带 `job_id` / `fund_code` / `source` / `stage` 上下文。

按规格书 4.3 要求:

- 跨模块日志统一携带业务上下文(job_id / fund_code / source / stage)
- 日志不得包含 API key、数据库密码、完整持仓或未经脱敏的外部响应

通过 `get_logger(__name__, default_context={...})` 拿到一个绑定默认上下文的
logger;每次记录时通过 `.info(..., extra={"job_id": ...})` 或用 `bind()`
返回的子 logger 携带额外字段。输出格式由 root logger 的 `Formatter` 决定,
但我们统一通过 `format_with_context` 把上下文拼到消息前部。
"""
from __future__ import annotations

import logging
from typing import Any

from backend.exceptions import redact_dict


_STANDARD_CONTEXT_FIELDS: tuple[str, ...] = (
    "job_id",
    "fund_code",
    "source",
    "stage",
    "trigger",
)


class ContextLogger:
    """绑定默认上下文的 logger wrapper。

    每次记录时,默认上下文会被合并进消息前缀;敏感字段会被 redact。

    Usage:
        log = get_logger(__name__, default_context={"stage": "ingest"})
        log.info("processing", extra={"fund_code": "110011"})
        # → "[stage=ingest fund_code=110011] processing"

        child = log.bind(job_id="abc123")
        child.warning("slow")  # 自动带 job_id=abc123
    """

    def __init__(
        self,
        underlying: logging.Logger,
        default_context: dict[str, Any] | None = None,
    ) -> None:
        self._log = underlying
        self._ctx = dict(default_context or {})

    def bind(self, **extra: Any) -> "ContextLogger":
        merged = {**self._ctx, **self._kwargs(extra)}
        return ContextLogger(self._log, default_context=merged)

    def _kwargs(self, extra: Any) -> dict[str, Any]:
        if extra is None:
            return {}
        if not isinstance(extra, dict):
            return {"extra": extra}
        return extra

    def _format_msg(self, msg: str, ctx: dict[str, Any]) -> str:
        if not ctx:
            return str(msg)
        prefix = " ".join(f"{k}={_safe(v)}" for k, v in sorted(ctx.items()))
        return f"[{prefix}] {msg}"

    def _log_at(
        self,
        level: int,
        msg: object,
        *args: Any,
        extra: dict[str, Any] | None = None,
        stacklevel: int = 2,
    ) -> None:
        merged_ctx = {**self._ctx, **self._kwargs(extra)}
        # 过滤已知上下文字段;其余作为 `extra_*` 拼到 prefix
        standard = {k: merged_ctx.pop(k) for k in list(merged_ctx) if k in _STANDARD_CONTEXT_FIELDS}
        any_extra = merged_ctx
        clean = {**standard, **any_extra}
        clean = redact_dict(clean)  # type: ignore[arg-type]
        formatted = self._format_msg(msg, clean)
        self._log.log(level, formatted, *args, stacklevel=stacklevel)

    def debug(
        self,
        msg: object,
        *args: Any,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._log_at(logging.DEBUG, msg, *args, extra=extra, stacklevel=3)

    def info(
        self,
        msg: object,
        *args: Any,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._log_at(logging.INFO, msg, *args, extra=extra, stacklevel=3)

    def warning(
        self,
        msg: object,
        *args: Any,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._log_at(logging.WARNING, msg, *args, extra=extra, stacklevel=3)

    def error(
        self,
        msg: object,
        *args: Any,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._log_at(logging.ERROR, msg, *args, extra=extra, stacklevel=3)

    def exception(
        self,
        msg: object,
        *args: Any,
        extra: dict[str, Any] | None = None,
    ) -> None:
        # 与 logging.Logger.exception 一致,默认 ERROR + exc_info=True
        merged_ctx = {**self._ctx, **self._kwargs(extra)}
        standard = {k: merged_ctx.pop(k) for k in list(merged_ctx) if k in _STANDARD_CONTEXT_FIELDS}
        clean = redact_dict({**standard, **merged_ctx})  # type: ignore[arg-type]
        formatted = self._format_msg(msg, clean)
        self._log.error(formatted, *args, exc_info=True, stacklevel=3)


def _safe(value: Any) -> str:
    """把任意上下文值转成字符串;非 ASCII 安全。"""
    try:
        return str(value)
    except Exception:
        return "<unrepr>"


def get_logger(
    name: str,
    *,
    default_context: dict[str, Any] | None = None,
) -> ContextLogger:
    """拿一个绑定默认上下文的 logger。"""
    return ContextLogger(logging.getLogger(name), default_context=default_context)


def get_standard_logger(name: str) -> ContextLogger:
    """拿一个不带默认上下文的 ContextLogger,等价于 `logging.getLogger` 的友好包装。"""
    return get_logger(name)


__all__ = [
    "ContextLogger",
    "get_logger",
    "get_standard_logger",
]