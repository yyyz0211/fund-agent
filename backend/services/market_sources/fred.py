"""FredSeriesAdapter: 用 FRED 公开 CSV/JSON 端点抓宏观序列最新观测。

公开 CSV URL: https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}
公开 JSON URL: 通过向 csv 端点简单替换扩展或使用内部 API;测试期望 input 是
    '{"observations":[{"date":"2026-07-06","value":"4.25"}]}'
adapter 不强制区分, 先按 JSON 试, 失败按 CSV 试; 两者都不行 → [].
返回:
    [{
        "category": "macro",
        "source": "FRED",
        "source_url": "https://fred.stlouisfed.org/series/{series_id}",
        "title": <title 参数>,
        "summary": "{series_id} latest observation {date} = {value}",
        "symbols": [series_id],
        "metrics": {"value": float, "date": YYYY-MM-DD},
        ...
    }]

失败一律返回 []。
"""
from __future__ import annotations

import csv
import json
from io import StringIO


_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


class FredSeriesAdapter:
    def __init__(self, *, series_id: str, title: str):
        self.series_id = series_id
        self.title = title

    def fetch(self, *, client, trade_date: str, brief_type: str = "pre_market") -> list[dict]:
        try:
            resp = client.get(_FRED_CSV_URL, params={"id": self.series_id}, timeout=10.0)
            text = getattr(resp, "text", "") or ""
            if not text:
                return []
            return self._parse(text, trade_date=trade_date, brief_type=brief_type)
        except Exception:
            return []

    def _parse(self, raw: str, *, trade_date: str, brief_type: str) -> list[dict]:
        obs = self._parse_observations(raw)
        if not obs:
            return []
        obs_sorted = sorted(obs, key=lambda o: o.get("date") or "")
        last = obs_sorted[-1]
        date = last.get("date") or trade_date
        value = last.get("value")
        if value is None:
            return []
        try:
            value_num = float(value)
        except (TypeError, ValueError):
            return []
        try:
            num_str = f"{value_num:g}"
        except Exception:
            num_str = str(value)
        date_str = str(date)[:10]
        return [{
            "trade_date": trade_date,
            "brief_type": brief_type,
            "category": "macro",
            "source": "FRED",
            "source_url": f"https://fred.stlouisfed.org/series/{self.series_id}",
            "title": self.title,
            "summary": f"{self.series_id} latest observation {date_str} = {num_str}",
            "symbols": [self.series_id],
            "metrics": {"value": value_num, "date": date_str},
            "published_at": date_str,
            "reliability": "official",
        }]

    def _parse_observations(self, raw: str) -> list[dict]:
        """先按 JSON 试, 再按 CSV 试。"""
        # JSON 尝试 (test_market_source_adapters.py 期望格式)
        stripped = raw.strip()
        if stripped.startswith("{"):
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict):
                    obs = obj.get("observations")
                    if isinstance(obs, list):
                        # [{date:..., value:...}] OR [{date:..., value:"4.25"}]
                        out = []
                        for r in obs:
                            if not isinstance(r, dict):
                                continue
                            d = r.get("date")
                            v = r.get("value")
                            if v in ("", None, "."):
                                continue
                            try:
                                v = float(v)
                            except (TypeError, ValueError):
                                continue
                            out.append({"date": d, "value": v})
                        return out
            except (json.JSONDecodeError, TypeError):
                pass
        # CSV 尝试 (production FRED 端点返回)
        try:
            reader = csv.DictReader(StringIO(raw))
            rows = [r for r in reader if r]
        except Exception:
            return []
        out: list[dict] = []
        for r in rows:
            # 找日期列和值列
            date_val = None
            num_val = None
            for k, v in r.items():
                if v in (None, ""):
                    continue
                if date_val is None and k and k.lower().endswith("date"):
                    date_val = v
                elif num_val is None:
                    try:
                        num_val = float(v)
                    except (TypeError, ValueError):
                        continue
            if date_val is not None and num_val is not None:
                out.append({"date": date_val, "value": num_val})
        return out