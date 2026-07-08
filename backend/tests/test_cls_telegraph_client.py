"""财联社电报客户端测试。"""
from __future__ import annotations

from datetime import datetime, timezone


def test_sign_params_matches_observed_cls_signature():
    from backend.services.cls_telegraph_client import sign_params

    params = {
        "refresh_type": 1,
        "rn": 5,
        "last_time": 1783482113,
        "os": "web",
        "sv": "8.7.9",
        "app": "CailianpressWeb",
    }

    assert sign_params(params) == "237f3789813b4aeb4bf302c9300c4d69"


def test_clean_html_text_removes_em_tags_and_collapses_space():
    from backend.services.cls_telegraph_client import clean_html_text

    text = "【南方<em>基</em><em>金</em>】\n\n  光通信&nbsp;赛道"

    assert clean_html_text(text) == "【南方基金】 光通信 赛道"


def test_parse_cls_time_accepts_seconds_millis_and_iso():
    from backend.services.cls_telegraph_client import parse_cls_time

    assert parse_cls_time(1783481506) == "2026-07-08 11:31:46"
    assert parse_cls_time(1783481506000) == "2026-07-08 11:31:46"
    assert parse_cls_time("2026-07-08T11:31:46+08:00") == "2026-07-08 11:31:46"


def test_parse_cls_time_falls_back_to_now():
    from backend.services.cls_telegraph_client import parse_cls_time

    fallback = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)

    assert parse_cls_time("bad", fallback=fallback) == "2026-07-08 20:00:00"


def test_normalize_telegraph_item_maps_symbols_and_metrics():
    from backend.services.cls_telegraph_client import normalize_telegraph_item

    item = {
        "id": 2420082,
        "title": "",
        "brief": "【午评】财联社7月8日电，市场回升。",
        "content": "财联社7月8日电，市场回升。",
        "ctime": 1783481506,
        "level": "B",
        "reading_num": 49031,
        "comment_num": 47,
        "share_num": 243,
        "images": ["https://image.cls.cn/a.jpg"],
        "audio_url": ["https://image.cls.cn/a.mp3"],
        "stock_list": [{"name": "科创50", "StockID": "sh000688"}],
        "subjects": [{"subject_name": "盘面直播"}],
    }

    row = normalize_telegraph_item(item, category="watch")

    assert row is not None
    assert row["title"] == "【午评】财联社7月8日电，市场回升。"
    assert row["summary"] == "【午评】财联社7月8日电，市场回升。"
    assert row["published_at"] == "2026-07-08 11:31:46"
    assert row["source"] == "财联社"
    assert row["source_url"] == "https://www.cls.cn/detail/2420082"
    assert row["symbols"] == ["科创50", "sh000688", "盘面直播"]
    assert row["metrics"]["cls_category"] == "watch"
    assert row["metrics"]["level"] == "B"
    assert row["metrics"]["images"] == ["https://image.cls.cn/a.jpg"]


# ---------------------------------------------------------------------------
# HTTP client tests
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.response


def test_fetch_roll_list_signs_and_normalizes_rows():
    from backend.services.cls_telegraph_client import fetch_roll_list

    client = _Client(_Response({
        "errno": 0,
        "data": {
            "roll_data": [{
                "id": 1,
                "title": "基金快讯",
                "brief": "内容",
                "ctime": 1783481506,
                "subjects": [],
                "stock_list": [],
            }]
        },
    }))

    rows = fetch_roll_list(client=client, category="fund", limit=5, last_time=1783482113)

    assert len(rows) == 1
    assert rows[0]["title"] == "基金快讯"
    method, url, kwargs = client.calls[0]
    assert method == "GET"
    assert url == "https://www.cls.cn/v1/roll/get_roll_list"
    params = kwargs["params"]
    assert params["app"] == "CailianpressWeb"
    assert params["os"] == "web"
    assert params["sv"] == "8.7.9"
    assert params["category"] == "fund"
    assert params["rn"] == 5
    assert params["last_time"] == 1783482113
    assert "sign" in params
    assert kwargs["headers"]["Referer"] == "https://www.cls.cn/telegraph"


def test_fetch_roll_list_returns_empty_on_bad_response():
    from backend.services.cls_telegraph_client import fetch_roll_list

    client = _Client(_Response({"errno": "10012", "msg": "签名错误"}))

    assert fetch_roll_list(client=client, category="fund", limit=5) == []


def test_search_telegraph_posts_body_and_normalizes_rows():
    from backend.services.cls_telegraph_client import search_telegraph

    client = _Client(_Response({
        "list": [{
            "id": 2,
            "title": "南方基金 ETF",
            "content": "基金内容",
            "ctime": 1783481989,
        }],
        "total": 1,
    }))

    rows = search_telegraph(client=client, keyword="基金", category="fund", limit=10)

    assert rows[0]["title"] == "南方基金 ETF"
    method, url, kwargs = client.calls[0]
    assert method == "POST"
    assert url == "https://www.cls.cn/api/csw"
    assert kwargs["json"]["keyword"] == "基金"
    assert kwargs["json"]["category"] == "fund"
    assert kwargs["params"]["sign"]
