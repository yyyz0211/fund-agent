"""briefing_service 集成测试。

TDD 顺序:写失败测试 → 跑确认失败 → 实现 → 跑确认通过。
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.db.session import Base


# ---------------------------------------------------------------------------
# In-memory session fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def in_memory_session():
    """每次测试用独立 in-memory SQLite + 干净 schema。"""
    from backend.db.models import Briefing  # noqa: F401  注册入 Base.metadata

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Task 1: Briefing ORM round-trip
# ---------------------------------------------------------------------------

class TestBriefingModel:
    """Briefing ORM 写入/读回/唯一约束验证。"""

    def test_briefing_model_round_trip(self, in_memory_session):
        """写入一条 Briefing 再读回,所有字段正确。"""
        # import inside to allow the model to be added later
        from backend.db.models import Briefing

        today = "2026-07-07"
        now = datetime.now().isoformat()
        row = Briefing(
            briefing_date=today,
            title="今日基金简报 2026-07-07",
            markdown="# 今日行情\n\n沪深300上涨0.5%",
            sections_json='{"market_snapshot":[],"watchlist_changes":[]}',
            source="akshare + deepseek",
            as_of=today,
        )
        in_memory_session.add(row)
        in_memory_session.commit()

        found = in_memory_session.query(Briefing).filter_by(briefing_date=today).first()
        assert found is not None
        assert found.title == "今日基金简报 2026-07-07"
        assert "沪深300上涨0.5%" in found.markdown
        assert found.source == "akshare + deepseek"
        assert found.as_of == today

    def test_briefing_unique_on_briefing_date(self, in_memory_session):
        """同日再插入应抛 IntegrityError(uq_briefing_date)。"""
        from backend.db.models import Briefing

        today = "2026-07-07"
        in_memory_session.add(Briefing(
            briefing_date=today, title="第一篇",
            markdown="x", sections_json="{}", source=None, as_of=None,
        ))
        in_memory_session.commit()

        # 第二次插入同一 briefing_date
        in_memory_session.add(Briefing(
            briefing_date=today, title="第二篇",
            markdown="y", sections_json="{}", source=None, as_of=None,
        ))
        with pytest.raises(IntegrityError):
            in_memory_session.commit()

    def test_briefing_sections_json_round_trip(self, in_memory_session):
        """中文 key/value 在 sections_json 序列化/反序列化后正确。"""
        from backend.db.models import Briefing
        import json

        snapshot = {
            "market_snapshot": [
                {"symbol": "000300", "name": "沪深300", "close": 3800.5, "change_pct": 0.52}
            ],
            "watchlist_changes": [
                {"fund_code": "110011", "fund_name": "易方达蓝筹精选",
                 "period_returns": {"1d": -0.02, "1w": 0.05, "1m": 0.08}}
            ],
            "errors": [],
        }
        json_str = json.dumps(snapshot, ensure_ascii=False)

        row = Briefing(
            briefing_date="2026-07-07", title="Test",
            markdown="test", sections_json=json_str,
            source=None, as_of=None,
        )
        in_memory_session.add(row)
        in_memory_session.commit()

        found = in_memory_session.query(Briefing).first()
        loaded = json.loads(found.sections_json)
        assert loaded["market_snapshot"][0]["name"] == "沪深300"
        assert loaded["watchlist_changes"][0]["period_returns"]["1m"] == 0.08


# ---------------------------------------------------------------------------
# Task 2: collect_watchlist_snapshot
# ---------------------------------------------------------------------------

class TestCollectWatchlistSnapshot:
    """数据收集:指数 + 自选池 metrics。"""

    def test_collect_returns_market_and_watchlist_metrics(self):
        """mock market + watchlist + fund_service,断言返回结构正确。"""
        from backend.services import briefing_service

        market_rows = [
            {"symbol": "000300", "name": "沪深300", "close": 3800.0, "change_pct": 0.5,
             "market_date": "2026-07-07", "source": "akshare"},
            {"symbol": "000001", "name": "上证指数", "close": 3200.0, "change_pct": 0.3,
             "market_date": "2026-07-07", "source": "akshare"},
        ]
        watchlist_rows = [
            {"fund_code": "110011", "fund_name": "易方达蓝筹精选"},
            {"fund_code": "000001", "fund_name": "平安领先"},
            {"fund_code": "001594", "fund_name": "东财券商指数"},
        ]
        fund_metrics_1d = {"period": "1d", "period_return": -0.02, "nav_date": "2026-07-07"}
        fund_metrics_1w = {"period": "1w", "period_return": 0.05}
        fund_metrics_1m = {"period": "1m", "period_return": 0.08}

        def mock_get_indices():
            return {"indices": market_rows, "source": "akshare", "as_of": "2026-07-07"}

        def mock_list_watchlist(**_kwargs):
            return watchlist_rows

        def mock_get_metrics(fund_code, period, **_kwargs):
            if period == "1d":
                return fund_metrics_1d
            elif period == "1w":
                return fund_metrics_1w
            else:
                return fund_metrics_1m

        with patch.object(briefing_service, "_collect_market_snapshot", mock_get_indices), \
             patch("backend.services.briefing_service.watchlist_service.list_watchlist", mock_list_watchlist), \
             patch("backend.services.briefing_service.fund_service.get_metrics", mock_get_metrics):

            result = briefing_service.collect_watchlist_snapshot()

        assert "market_snapshot" in result
        assert "watchlist_changes" in result
        assert "errors" in result
        assert "collect_meta" in result
        assert len(result["market_snapshot"]) == 2
        assert len(result["watchlist_changes"]) == 3
        assert result["errors"] == []
        assert result["collect_meta"]["max_funds_applied"] is None  # 未超限额

    def test_collect_skips_failed_fund_continues_loop(self):
        """单只 fund 抛异常:记 errors,后续继续处理。"""
        from backend.services import briefing_service

        def mock_get_indices():
            return {"indices": [], "source": "akshare", "as_of": "2026-07-07"}

        def mock_list_watchlist(**_kwargs):
            return [
                {"fund_code": "110011", "fund_name": "A"},
                {"fund_code": "000001", "fund_name": "B"},
                {"fund_code": "001594", "fund_name": "C"},
            ]

        call_count = 0

        def mock_get_metrics(fund_code, period, **_kwargs):
            nonlocal call_count
            call_count += 1
            if fund_code == "000001":
                raise ValueError("网络超时")
            return {"period": period, "period_return": 0.01}

        with patch.object(briefing_service, "_collect_market_snapshot", mock_get_indices), \
             patch("backend.services.briefing_service.watchlist_service.list_watchlist", mock_list_watchlist), \
             patch("backend.services.briefing_service.fund_service.get_metrics", mock_get_metrics):

            result = briefing_service.collect_watchlist_snapshot()

        assert len(result["watchlist_changes"]) == 2
        assert result["watchlist_changes"][0]["fund_code"] == "110011"
        assert len(result["errors"]) == 1
        assert result["errors"][0]["fund_code"] == "000001"
        assert result["errors"][0]["stage"] == "collect"
        assert "网络超时" in result["errors"][0]["message"]
        # 每只基金先调 1d,失败则跳整只；2 只全成功=2*3=6,1 只 1d 失败=1 → 共 7
        assert call_count == 7

    def test_collect_caps_max_watchlist_funds(self):
        """自选池超出限额时只采集前 N 只,并在 meta 留 warning。"""
        from backend.services import briefing_service

        def mock_get_indices():
            return {"indices": [], "source": "akshare", "as_of": "2026-07-07"}

        def mock_list_watchlist(**_kwargs):
            return [{"fund_code": f"00{i:04d}", "fund_name": f"基金{i}"}
                    for i in range(1, 11)]

        def mock_get_metrics(fund_code, period, **_kwargs):
            return {"period": period, "period_return": 0.01}

        cap = 3

        with patch.object(briefing_service, "_collect_market_snapshot", mock_get_indices), \
             patch("backend.services.briefing_service.watchlist_service.list_watchlist", mock_list_watchlist), \
             patch("backend.services.briefing_service.fund_service.get_metrics", mock_get_metrics), \
             patch("backend.services.briefing_service.settings") as mock_settings:

            mock_settings.briefing_max_watchlist_funds = cap
            result = briefing_service.collect_watchlist_snapshot()

        assert len(result["watchlist_changes"]) == cap
        assert any("截断" in w or "cap" in w.lower()
                   for w in result["collect_meta"].get("warnings", []))


# ---------------------------------------------------------------------------
# Task 3: compose_briefing
# ---------------------------------------------------------------------------

class TestComposeBriefing:
    """简报合成:mock LLM,验证 prompt 和解析逻辑。"""

    def test_compose_returns_markdown_and_sections(self):
        """LLM 返回合法 JSON 时正确解析 markdown + sections。"""
        from backend.services import briefing_service
        from langchain_core.messages import AIMessage

        llm_content = '{"markdown": "# 今日简报\\n\\n沪深300+0.5%", "sections": {"market_snapshot": [], "watchlist_changes": []}}'

        class FakeModel:
            def invoke(self, _prompt):
                return AIMessage(content=llm_content)

        with patch("backend.services.briefing_service.build_model", return_value=FakeModel()):
            result = briefing_service.compose_briefing(
                {"market_snapshot": [], "watchlist_changes": []}
            )

        assert "markdown" in result
        assert "# 今日简报" in result["markdown"]
        assert "sections" in result
        assert "llm_model" in result
        assert result["warnings"] == []

    def test_compose_handles_invalid_llm_json(self):
        """LLM 返回非 JSON 纯文本时:markdown=原文本,sections={},warnings 追加。"""
        from backend.services import briefing_service
        from langchain_core.messages import AIMessage

        raw_text = "今日沪深300上涨,自选池表现平稳。"

        class FakeModel:
            def invoke(self, _prompt):
                return AIMessage(content=raw_text)

        with patch("backend.services.briefing_service.build_model", return_value=FakeModel()):
            result = briefing_service.compose_briefing({})

        assert result["markdown"] == raw_text
        assert result["sections"] == {}
        assert any("non_json" in w or "invalid" in w for w in result["warnings"])

    def test_compose_prompt_excludes_policy_blocks(self):
        """prompt 中出现「不构成投资建议」,不出现 policy 红线词。"""
        from backend.services import briefing_service
        from langchain_core.messages import AIMessage

        prompt_captured = []

        class FakeModel:
            def invoke(self, prompt):
                prompt_captured.append(str(prompt))
                return AIMessage(content='{"markdown":"ok","sections":{}}')

        with patch("backend.services.briefing_service.build_model", return_value=FakeModel()):
            briefing_service.compose_briefing({})

        full_prompt = "\n".join(prompt_captured)
        # 正面:必须有简报约束
        assert "不构成投资建议" in full_prompt
        # 负面:不能有"建议加仓"作为肯定性指导语气出现 —— 在禁止清单里
        # 出现是允许的(把它列为禁止词),但不允许在正面的"应当"语境中出现。
        # 检查不能出现"应当加仓 / 请加仓 / 必须加仓"之类的肯定语气。
        for forbidden in ["应当加仓", "请加仓", "必须加仓", "应当减仓", "请减仓", "必须减仓"]:
            assert forbidden not in full_prompt
        # 且 prompt 里要明确出现"禁止"章节(负面词表的上下文是禁止)
        assert "禁止" in full_prompt


# ---------------------------------------------------------------------------
# Task 4: run_daily_briefing
# ---------------------------------------------------------------------------

class TestRunDailyBriefing:
    """主流程:collect → compose → upsert Briefing。"""

    def test_run_writes_briefing_row(self, in_memory_session):
        """mock collect+compose,跑完确认落库一条。"""
        from backend.db.models import Briefing
        from backend.services import briefing_service

        snapshot = {
            "market_snapshot": [{"symbol": "000300", "name": "沪深300", "close": 3800.0, "change_pct": 0.5}],
            "watchlist_changes": [],
            "errors": [],
            "collect_meta": {},
        }
        compose_result = {
            "markdown": "# 今日简报\n\n沪深300+0.5%",
            "sections": {"market_snapshot": [], "watchlist_changes": []},
            "warnings": [],
            "llm_model": "deepseek-chat",
        }

        def mock_collect(**_kwargs):
            return snapshot

        def mock_compose(snap):
            assert snap == snapshot
            return compose_result

        with patch.object(briefing_service, "collect_watchlist_snapshot", mock_collect), \
             patch.object(briefing_service, "compose_briefing", mock_compose):

            briefing_service.reset_for_tests()
            result = briefing_service.run_daily_briefing(
                trigger="manual", session=in_memory_session
            )

        rows = in_memory_session.query(Briefing).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.source == "akshare + deepseek"
        assert "沪深300" in row.markdown
        assert result["trigger"] == "manual"
        assert result["succeeded"] == 1

    def test_run_idempotent_same_day(self, in_memory_session):
        """同日两次 run:总行数仍=1,updated_at 改变。"""
        from backend.db.models import Briefing
        from backend.services import briefing_service
        import time

        def make_snapshot(md_text):
            return {
                "market_snapshot": [{"symbol": "000300", "name": "沪深300", "close": 3800.0, "change_pct": 0.5}],
                "watchlist_changes": [{"fund_code": "110011", "fund_name": "A"}],
                "errors": [],
                "collect_meta": {},
            }, {"markdown": md_text, "sections": {}, "warnings": [], "llm_model": "test"}

        snap_v1, comp_v1 = make_snapshot("v1 content")
        snap_v2, comp_v2 = make_snapshot("v2 content")

        def mock_collect(**_kwargs):
            return snap_v1

        def mock_compose(snap):
            return comp_v1

        briefing_service.reset_for_tests()

        with patch.object(briefing_service, "collect_watchlist_snapshot", mock_collect), \
             patch.object(briefing_service, "compose_briefing", mock_compose):
            briefing_service.run_daily_briefing(trigger="manual", session=in_memory_session)

        time.sleep(0.01)  # 确保 updated_at 能区分

        def mock_compose_v2(snap):
            return comp_v2

        with patch.object(briefing_service, "collect_watchlist_snapshot", mock_collect), \
             patch.object(briefing_service, "compose_briefing", mock_compose_v2):
            briefing_service.run_daily_briefing(trigger="manual", session=in_memory_session)

        rows = in_memory_session.query(Briefing).all()
        assert len(rows) == 1
        assert "v2" in rows[0].markdown  # 最新版本

    def test_run_records_last_run_snapshot(self, in_memory_session):
        """跑完后 get_last_run() 返回正确快照。"""
        from backend.services import briefing_service

        def mock_collect(**_kwargs):
            return {
                "market_snapshot": [{"symbol": "000300"}],
                "watchlist_changes": [{"fund_code": "110011"}],
                "errors": [],
                "collect_meta": {},
            }

        def mock_compose(snap):
            return {"markdown": "x", "sections": {}, "warnings": [], "llm_model": "test"}

        with patch.object(briefing_service, "collect_watchlist_snapshot", mock_collect), \
             patch.object(briefing_service, "compose_briefing", mock_compose):

            briefing_service.reset_for_tests()
            briefing_service.run_daily_briefing(trigger="test_run", session=in_memory_session)
            last = briefing_service.get_last_run()

        assert last["trigger"] == "test_run"
        assert "last_run_at" in last
        assert last["succeeded"] == 1
        assert last["failed"] == 0
        assert last["total_funds"] == 1

    def test_run_records_failures_when_collect_errors(self, in_memory_session):
        """collect 失败项进入 failures,failed>0。"""
        from backend.db.models import Briefing
        from backend.services import briefing_service

        def mock_collect(**_kwargs):
            return {
                "market_snapshot": [],
                "watchlist_changes": [{"fund_code": "110011", "fund_name": "A"}],
                "errors": [{"fund_code": "000001", "stage": "collect", "message": "timeout"}],
                "collect_meta": {},
            }

        def mock_compose(snap):
            return {"markdown": "ok", "sections": {}, "warnings": [], "llm_model": "test"}

        briefing_service.reset_for_tests()

        with patch.object(briefing_service, "collect_watchlist_snapshot", mock_collect), \
             patch.object(briefing_service, "compose_briefing", mock_compose):

            result = briefing_service.run_daily_briefing(trigger="manual", session=in_memory_session)

        assert result["failed"] == 1
        assert result["failed"] >= 1
        assert any(f.get("fund_code") == "000001" for f in result["failures"])
        # compose 仍能跑（因为 collect 返回了非空 watchlist_changes + market_snapshot）
        # 但我们这里 mock 返回的 watchlist_changes 长度=1（"110011"）,
        # 单纯说明 failures 里有 000001 即可。
        assert any(f.get("stage") == "collect" for f in result["failures"])

    def test_run_returns_empty_briefing_when_no_watchlist(self, in_memory_session):
        """自选池为空:markdown 为占位符,不抛异常。"""
        from backend.db.models import Briefing
        from backend.services import briefing_service

        def mock_collect(**_kwargs):
            return {
                "market_snapshot": [],
                "watchlist_changes": [],
                "errors": [],
                "collect_meta": {},
            }

        briefing_service.reset_for_tests()

        with patch.object(briefing_service, "collect_watchlist_snapshot", mock_collect):
            result = briefing_service.run_daily_briefing(trigger="manual", session=in_memory_session)

        assert result["succeeded"] == 0
        rows = in_memory_session.query(Briefing).all()
        assert len(rows) == 1
        assert "自选池为空" in rows[0].markdown
        assert result["last_run_at"] is not None
