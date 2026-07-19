"""P1 本地规则 LLM 提供器。"""

from __future__ import annotations

from review.analyzer import ReviewAnalysis


class LocalRuleProvider:
    """Minimal deterministic provider for P1 reviews."""

    def summarize(self, analysis: ReviewAnalysis) -> str:
        """Summarize a review analysis deterministically."""
        return f"{analysis.trade_date}: {len(analysis.findings)} findings"
