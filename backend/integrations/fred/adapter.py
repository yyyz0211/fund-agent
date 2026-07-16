"""FRED public series observations to market-evidence rows."""
from __future__ import annotations

import csv
import json
from io import StringIO


_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


class FredSeriesAdapter:
    def __init__(self, *, series_id: str, title: str):
        self.series_id = series_id
        self.title = title

    def fetch(
        self,
        *,
        client,
        trade_date: str,
        brief_type: str = "pre_market",
    ) -> list[dict]:
        try:
            response = client.get(
                _FRED_CSV_URL,
                params={"id": self.series_id},
                timeout=10.0,
            )
            text = getattr(response, "text", "") or ""
            if not text:
                return []
            return self._parse(
                text,
                trade_date=trade_date,
                brief_type=brief_type,
            )
        except Exception:
            return []

    def _parse(
        self,
        raw: str,
        *,
        trade_date: str,
        brief_type: str,
    ) -> list[dict]:
        observations = self._parse_observations(raw)
        if not observations:
            return []
        observations_sorted = sorted(
            observations,
            key=lambda observation: observation.get("date") or "",
        )
        last = observations_sorted[-1]
        observation_date = last.get("date") or trade_date
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
        date_str = str(observation_date)[:10]
        return [{
            "trade_date": trade_date,
            "brief_type": brief_type,
            "category": "macro",
            "source": "FRED",
            "source_url": f"https://fred.stlouisfed.org/series/{self.series_id}",
            "title": self.title,
            "summary": (
                f"{self.series_id} latest observation {date_str} = {num_str}"
            ),
            "symbols": [self.series_id],
            "metrics": {"value": value_num, "date": date_str},
            "published_at": date_str,
            "reliability": "official",
        }]

    def _parse_observations(self, raw: str) -> list[dict]:
        """Try JSON observations first, then the production CSV format."""
        stripped = raw.strip()
        if stripped.startswith("{"):
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict):
                    observations = obj.get("observations")
                    if isinstance(observations, list):
                        out = []
                        for row in observations:
                            if not isinstance(row, dict):
                                continue
                            observation_date = row.get("date")
                            value = row.get("value")
                            if value in ("", None, "."):
                                continue
                            try:
                                value = float(value)
                            except (TypeError, ValueError):
                                continue
                            out.append({"date": observation_date, "value": value})
                        return out
            except (json.JSONDecodeError, TypeError):
                pass
        try:
            reader = csv.DictReader(StringIO(raw))
            rows = [row for row in reader if row]
        except Exception:
            return []
        out: list[dict] = []
        for row in rows:
            date_value = None
            number_value = None
            for key, value in row.items():
                if value in (None, ""):
                    continue
                if date_value is None and key and key.lower().endswith("date"):
                    date_value = value
                elif number_value is None:
                    try:
                        number_value = float(value)
                    except (TypeError, ValueError):
                        continue
            if date_value is not None and number_value is not None:
                out.append({"date": date_value, "value": number_value})
        return out
