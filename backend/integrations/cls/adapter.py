"""CLS telegraph rows to market-evidence rows."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx


FetchClsRollList = Callable[..., list[dict[str, Any]]]


def _parse_categories(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return ["fund", "watch", "announcement", "hk_us", "red", "remind"]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


class ClsTelegraphAdapter:
    source = "财联社"
    reliability = "wire"
    category = "news"

    def __init__(
        self,
        *,
        fetch_roll_list: FetchClsRollList,
        app_version: str,
        client: Any | None = None,
        categories: str | list[str] | tuple[str, ...] | None = None,
        per_category_limit: int = 10,
        timeout_seconds: float = 15.0,
        max_attempts: int = 1,
        retry_base_seconds: float = 1.0,
    ):
        self._fetch_roll_list = fetch_roll_list
        self.client = client
        self.categories = _parse_categories(categories)
        self.per_category_limit = max(1, int(per_category_limit))
        self.timeout_seconds = float(timeout_seconds)
        self.app_version = app_version
        self.max_attempts = max(1, int(max_attempts))
        self.retry_base_seconds = float(retry_base_seconds)
        self.last_errors: list[dict] = []

    def _to_evidence(
        self,
        row: dict,
        *,
        trade_date: str,
        brief_type: str,
    ) -> dict | None:
        if not (row.get("source_url") and row.get("title")):
            return None
        return {
            "trade_date": trade_date,
            "brief_type": brief_type,
            "category": self.category,
            "title": row["title"],
            "summary": row.get("summary") or "",
            "symbols": row.get("symbols") or [],
            "metrics": row.get("metrics") or {},
            "source": self.source,
            "source_url": row["source_url"],
            "published_at": row.get("published_at"),
            "reliability": self.reliability,
        }

    def fetch(
        self,
        *,
        client=None,
        trade_date: str,
        brief_type: str = "post_market",
    ) -> list[dict]:
        """Fetch configured CLS categories without leaking source failures."""
        active_client = client or self.client
        owns_client = active_client is None
        if active_client is None:
            active_client = httpx.Client(
                follow_redirects=True,
                timeout=self.timeout_seconds,
            )
        out: list[dict] = []
        self.last_errors = []
        try:
            for category in self.categories:
                try:
                    rows = self._fetch_roll_list(
                        client=active_client,
                        category=category,
                        limit=self.per_category_limit,
                        timeout_seconds=self.timeout_seconds,
                        app_version=self.app_version,
                        diagnostics=self.last_errors,
                        max_attempts=self.max_attempts,
                        retry_base_seconds=self.retry_base_seconds,
                    )
                except Exception as exc:  # noqa: BLE001
                    self.last_errors.append({
                        "category": category,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    continue
                for row in rows:
                    evidence = self._to_evidence(
                        row,
                        trade_date=trade_date,
                        brief_type=brief_type,
                    )
                    if evidence is not None:
                        out.append(evidence)
            return out
        except Exception:
            return []
        finally:
            if owns_client:
                try:
                    active_client.close()
                except Exception:
                    pass
