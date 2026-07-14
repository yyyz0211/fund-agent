"""Briefing composer: LLM 编排."""
from __future__ import annotations

# Re-export from module_briefing for compatibility
from backend.services.briefing.module_briefing import compose_briefing_v2

__all__ = ["compose_briefing_v2"]
