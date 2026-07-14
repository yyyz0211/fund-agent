"""统一异常体系 + 日志脱敏 + HTTP 状态码映射测试(spec 4.3)。"""
from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.exceptions import (
    DatabaseConflictError,
    DataSourceError,
    DataSourceTimeoutError,
    DependencyUnavailableError,
    FundAgentError,
    InputValidationError,
    ResourceNotFoundError,
    http_status_for,
    redact_dict,
    redact_string,
)
from backend.logging_utils import ContextLogger, get_logger


# ---------------------------------------------------------------------------
# 异常层级
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    def test_root_inheritance(self) -> None:
        for cls in (
            ResourceNotFoundError,
            InputValidationError,
            DataSourceError,
            DataSourceTimeoutError,
            DatabaseConflictError,
            DependencyUnavailableError,
        ):
            assert issubclass(cls, FundAgentError)
            assert issubclass(cls, Exception)

    def test_data_source_timeout_is_data_source(self) -> None:
        assert issubclass(DataSourceTimeoutError, DataSourceError)

    def test_details_passthrough(self) -> None:
        exc = InputValidationError("bad", field="x", details={"got": 1})
        assert exc.details == {"got": 1}
        assert exc.field == "x"

    def test_data_source_carries_source(self) -> None:
        exc = DataSourceError("boom", source="akshare", details={"k": 1})
        assert exc.source == "akshare"
        assert exc.details == {"k": 1}

    def test_dependency_carries_fallback(self) -> None:
        exc = DependencyUnavailableError(
            "no pgvector",
            dependency="pgvector",
            fallback="lexical-only",
        )
        assert exc.dependency == "pgvector"
        assert exc.fallback == "lexical-only"


# ---------------------------------------------------------------------------
# HTTP 状态码映射
# ---------------------------------------------------------------------------


class TestHttpStatusMapping:
    @pytest.mark.parametrize(
        "exc_factory, expected_status",
        [
            (lambda: ResourceNotFoundError("nope"), 404),
            (lambda: InputValidationError("bad"), 422),
            (lambda: DataSourceError("boom", source="akshare"), 502),
            (lambda: DataSourceTimeoutError("slow", source="akshare"), 504),
            (lambda: DatabaseConflictError("conflict"), 409),
            (lambda: DependencyUnavailableError("no pg"), 503),
            (lambda: FundAgentError("generic"), 500),
        ],
    )
    def test_status_mapping(self, exc_factory, expected_status) -> None:
        assert http_status_for(exc_factory()) == expected_status


# ---------------------------------------------------------------------------
# 日志脱敏
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_redacts_openai_key(self) -> None:
        raw = "request failed: sk-abcdefghijklmnopqrstuvwxyz1234567890"
        out = redact_string(raw)
        assert "sk-abc" not in out
        assert "***" in out

    def test_redacts_github_pat(self) -> None:
        raw = "token=ghp_abcdefghijklmnopqrstuvwxyz1234"
        assert "ghp_" not in redact_string(raw)

    def test_redacts_aws_access_key(self) -> None:
        raw = "key=AKIAIOSFODNN7EXAMPLE"
        assert "AKIA" not in redact_string(raw)

    def test_redacts_dict_sensitive_keys(self) -> None:
        payload = {
            "api_key": "sk-abc123456789012345",
            "password": "hunter2",
            "result": {"nested": "value"},
        }
        redacted = redact_dict(payload)
        assert redacted["api_key"] == "***"
        assert redacted["password"] == "***"
        assert redacted["result"] == {"nested": "value"}
        # 原 dict 未被修改
        assert payload["api_key"] == "sk-abc123456789012345"

    def test_redacts_dict_key_inside_string(self) -> None:
        payload = {"text": "Authorization: Bearer sk-abcdef1234567890"}
        redacted = redact_dict(payload)
        assert "sk-abc" not in redacted["text"]

    def test_redacts_nested_list(self) -> None:
        payload = {"items": [{"api_key": "sk-test"}, {"x": 1}]}
        redacted = redact_dict(payload)
        assert redacted["items"][0]["api_key"] == "***"
        assert redacted["items"][1] == {"x": 1}

    def test_redacts_tuple(self) -> None:
        redacted = redact_dict(("ok", {"api_key": "x"}))
        assert isinstance(redacted, tuple)
        assert redacted[1]["api_key"] == "***"

    def test_depth_limit(self) -> None:
        nested: dict = {"a": 1}
        current = nested
        for _ in range(20):
            current["next"] = {"a": 1}
            current = current["next"]
        out = redact_dict(nested)
        # 应当不抛异常
        assert isinstance(out, dict)

    def test_non_string_passthrough(self) -> None:
        for value in (123, 1.5, True, None):
            assert redact_dict(value) == value


# ---------------------------------------------------------------------------
# ContextLogger
# ---------------------------------------------------------------------------


class TestContextLogger:
    def test_default_context_prefixed(self, caplog: pytest.LogCaptureFixture) -> None:
        log = get_logger("test.default_ctx", default_context={"stage": "ingest"})
        with caplog.at_level(logging.INFO, logger="test.default_ctx"):
            log.info("hello")
        text = caplog.text
        assert "[stage=ingest]" in text
        assert "hello" in text

    def test_extra_overrides(self, caplog: pytest.LogCaptureFixture) -> None:
        log = get_logger("test.extra", default_context={"stage": "ingest"})
        with caplog.at_level(logging.INFO, logger="test.extra"):
            log.info("processing", extra={"fund_code": "110011"})
        text = caplog.text
        assert "stage=ingest" in text
        assert "fund_code=110011" in text

    def test_bind_returns_sub_logger(self, caplog: pytest.LogCaptureFixture) -> None:
        log = get_logger("test.bind").bind(job_id="abc123", stage="ingest")
        with caplog.at_level(logging.INFO, logger="test.bind"):
            log.info("done")
        text = caplog.text
        assert "job_id=abc123" in text
        assert "stage=ingest" in text

    def test_redacts_sensitive_keys(self, caplog: pytest.LogCaptureFixture) -> None:
        log = get_logger("test.redact")
        with caplog.at_level(logging.INFO, logger="test.redact"):
            log.info("auth", extra={"api_key": "sk-abc123456789012345"})
        text = caplog.text
        assert "sk-abc" not in text
        assert "***" in text

    def test_exception_logs_with_exc_info(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        log = get_logger("test.exc")
        try:
            raise ValueError("boom")
        except ValueError:
            with caplog.at_level(logging.ERROR, logger="test.exc"):
                log.exception("failed")
        text = caplog.text
        assert "failed" in text
        assert "ValueError" in text
        assert "boom" in text


# ---------------------------------------------------------------------------
# API exception handler 集成(spec 4.3 错误处理矩阵)
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    """最小 FastAPI app,挂 4 个业务异常 handler + 一个未处理异常 handler。"""
    from backend.api.app import _register_exception_handlers  # noqa: WPS433

    app = FastAPI()
    _register_exception_handlers(app)

    @app.get("/not-found")
    def _not_found() -> None:
        raise ResourceNotFoundError("fund 110011 not found")

    @app.get("/bad-input")
    def _bad_input() -> None:
        raise InputValidationError("bad period", field="period")

    @app.get("/data-source")
    def _data_source() -> None:
        raise DataSourceError("akshare 5xx", source="akshare")

    @app.get("/data-source-timeout")
    def _data_source_timeout() -> None:
        raise DataSourceTimeoutError("akshare timeout", source="akshare")

    @app.get("/conflict")
    def _conflict() -> None:
        raise DatabaseConflictError("unique violation on watchlist.fund_code")

    @app.get("/dep-unavail")
    def _dep_unavail() -> None:
        raise DependencyUnavailableError(
            "no pgvector", dependency="pgvector", fallback="lexical"
        )

    @app.get("/boom")
    def _boom() -> None:
        raise RuntimeError("kaboom")

    return TestClient(app, raise_server_exceptions=False)


class TestApiExceptionHandlers:
    def test_resource_not_found_maps_to_404(self, client: TestClient) -> None:
        resp = client.get("/not-found")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "resource_not_found"
        assert "110011" in body["error"]["message"]

    def test_input_validation_maps_to_422(self, client: TestClient) -> None:
        resp = client.get("/bad-input")
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "input_validation"
        assert body["error"]["field"] == "period"

    def test_data_source_maps_to_502(self, client: TestClient) -> None:
        resp = client.get("/data-source")
        assert resp.status_code == 502
        body = resp.json()
        assert body["error"]["code"] == "data_source_error"

    def test_data_source_timeout_maps_to_504(self, client: TestClient) -> None:
        resp = client.get("/data-source-timeout")
        assert resp.status_code == 504
        assert resp.json()["error"]["code"] == "data_source_timeout"

    def test_database_conflict_maps_to_409(self, client: TestClient) -> None:
        resp = client.get("/conflict")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "database_conflict"

    def test_dependency_unavailable_maps_to_503(self, client: TestClient) -> None:
        resp = client.get("/dep-unavail")
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "dependency_unavailable"

    def test_unhandled_exception_maps_to_500(self, client: TestClient) -> None:
        resp = client.get("/boom")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "internal_error"
        assert "kaboom" in body["error"]["message"]


# ---------------------------------------------------------------------------
# metric_service 迁移验证(spec 4.3 迁移样例)
# ---------------------------------------------------------------------------


class TestMetricServiceMigration:
    def test_unsupported_period_raises_input_validation(self) -> None:
        from backend.services.shared.metric_service import period_return

        with pytest.raises(InputValidationError) as exc_info:
            period_return([1.0, 1.1], period="bogus")
        assert exc_info.value.field == "period"
        assert "allowed" in exc_info.value.details


class TestBuildModelMigration:
    def test_missing_key_raises_dependency_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock

        from backend.config.settings import get_settings
        from backend.graph import model as graph_model

        get_settings.cache_clear()  # type: ignore[attr-defined]
        fake_settings = MagicMock()
        fake_settings.deepseek_api_key = ""
        monkeypatch.setattr(graph_model, "get_settings", lambda: fake_settings)
        try:
            with pytest.raises(DependencyUnavailableError) as exc_info:
                graph_model.build_model()
            assert exc_info.value.dependency == "deepseek_api_key"
            assert exc_info.value.fallback
        finally:
            get_settings.cache_clear()  # type: ignore[attr-defined]