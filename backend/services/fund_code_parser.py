"""Fund code parsing helpers."""
from __future__ import annotations

import re


_FUND_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def extract_fund_codes(text: str) -> list[str]:
    """Return unique 6-digit fund codes in first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _FUND_CODE_RE.finditer(text or ""):
        code = match.group(1)
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def extract_primary_fund_code(text: str) -> str | None:
    """Return the first 6-digit fund code, or None."""
    codes = extract_fund_codes(text)
    return codes[0] if codes else None
