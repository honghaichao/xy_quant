"""纯复盘分析器。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from review.collector import ReviewRawData


@dataclass(slots=True)
class RotationTheme:
    category: str
    name: str
    net_amount: float = 0.0
    pct_chg: float | None = None
    limit_count: int | None = None
    symbols: list[str] = field(default_factory=list)
    note: str = ""


@dataclass(slots=True)
class RotationStructure:
    main: list[RotationTheme] = field(default_factory=list)
    secondary: list[RotationTheme] = field(default_factory=list)
    active: list[RotationTheme] = field(default_factory=list)
    failed: list[RotationTheme] = field(default_factory=list)
    active_symbols: list[str] = field(default_factory=list)
    failed_symbols: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReviewAnalysis:
    """复盘分析结果。"""

    trade_date: str
    findings: list[str]
    metrics: dict[str, Any]


class ReviewAnalyzer:
    """只做规则分析，不做采集、不做外部 IO。"""

    def analyze(self, raw: ReviewRawData) -> ReviewAnalysis:
        rotation = self._build_rotation_structure(raw)
        findings = self._build_findings(raw, rotation)
        metrics: dict[str, Any] = {
            "raw_data": asdict(raw),
            "summary": self._build_summary(raw),
            "rotation": asdict(rotation),
            "watchlist": self._build_watchlist(rotation, raw),
            "risk_flags": self._build_risk_flags(raw, rotation),
        }
        return ReviewAnalysis(
            trade_date=raw.trade_date.isoformat(),
            findings=findings,
            metrics=metrics,
        )

    def _build_summary(self, raw: ReviewRawData) -> dict[str, Any]:
        return {
            "limit_up": raw.limit_stats.get("limit_up", 0),
            "limit_down": raw.limit_stats.get("limit_down", 0),
            "breadth_net": raw.breadth.get("net", 0),
            "hot_concepts": [item.get("concept_name") for item in raw.hot_concepts],
        }

    def _build_rotation_structure(self, raw: ReviewRawData) -> RotationStructure:
        main = self._build_themes(raw.top_concepts_in[:4], "concept") or self._build_themes(raw.top_industries_in[:4], "industry")
        secondary = self._merge_themes(
            self._build_themes(raw.top_industries_in[:5], "industry"),
            self._build_themes(raw.hot_concepts[:5], "concept"),
            exclude=self._collect_names(main),
        )
        active = self._build_themes(raw.hot_concepts[:5], "concept")
        failed = self._build_themes(raw.top_concepts_out[:5], "concept") + self._build_themes(raw.top_industries_out[:5], "industry")
        return RotationStructure(
            main=main[:4],
            secondary=secondary[:6],
            active=active[:6],
            failed=failed[:6],
            active_symbols=self._collect_names(active),
            failed_symbols=self._collect_names(failed),
        )

    def _build_themes(self, items: Iterable[dict[str, Any]], category: str) -> list[RotationTheme]:
        themes: list[RotationTheme] = []
        for item in items:
            if category == "concept":
                name = str(item.get("concept_name") or "")
            elif category == "industry":
                name = str(item.get("industry_name") or "")
            else:
                name = ""
            if not name or not self._is_theme_name(name, category):
                continue
            themes.append(
                RotationTheme(
                    category=category,
                    name=name,
                    net_amount=float(item.get("net_amount") or item.get("main_inflow") or item.get("amount") or 0.0),
                    pct_chg=self._maybe_float(item.get("pct_chg")),
                    limit_count=self._maybe_int(item.get("limit_count") or item.get("limit_times")),
                    symbols=[str(item.get("ts_code") or item.get("name") or name)],
                    note=str(item.get("verdict") or item.get("note") or ""),
                )
            )
        return themes

    def _build_watchlist(self, rotation: RotationStructure, raw: ReviewRawData) -> list[str]:
        candidates = self._dedupe(
            [
                *(theme.name for theme in rotation.main),
                *(theme.name for theme in rotation.secondary),
                *(theme.name for theme in rotation.active),
                *(theme.name for theme in rotation.failed),
                *(item.get("concept_name") for item in raw.prev_hot_review if item.get("concept_name")),
                *(item.get("concept_name") for item in raw.hot_concepts if item.get("concept_name")),
            ]
        )
        return candidates[:8]

    def _build_risk_flags(self, raw: ReviewRawData, rotation: RotationStructure) -> list[str]:
        flags: list[str] = []
        if raw.limit_stats.get("broken_rate", 0) > 0.35:
            flags.append("炸板率偏高")
        if raw.breadth.get("net", 0) < 0:
            flags.append("市场宽度偏弱")
        if not rotation.main:
            flags.append("主线不清晰")
        if not raw.hot_concepts:
            flags.append("热点断层")
        return flags

    def _build_findings(self, raw: ReviewRawData, rotation: RotationStructure) -> list[str]:
        findings: list[str] = []
        if raw.limit_stats.get("limit_up", 0) >= 1:
            findings.append(f"当日涨停 {raw.limit_stats.get('limit_up', 0)} 家。")
        if raw.breadth.get("net", 0) > 0:
            findings.append(f"市场宽度偏强，净广度 {raw.breadth.get('net', 0)}。")
        if rotation.main:
            findings.append("主线确认：" + " / ".join(theme.name for theme in rotation.main[:3]) + "。")
        if rotation.active:
            findings.append("活口观察：" + " / ".join(theme.name for theme in rotation.active[:3]) + "。")
        if rotation.failed:
            findings.append("失败轮动：" + " / ".join(theme.name for theme in rotation.failed[:3]) + "。")
        if raw.hot_concepts:
            findings.append(f"热点概念包括：{', '.join(item.get('concept_name', '') for item in raw.hot_concepts[:3])}。")
        return findings or ["当日无显著规则信号。"]

    def _merge_themes(self, *groups: list[RotationTheme], exclude: list[str] | None = None) -> list[RotationTheme]:
        seen = set(exclude or [])
        merged: list[RotationTheme] = []
        for group in groups:
            for theme in group:
                if theme.name in seen:
                    continue
                seen.add(theme.name)
                merged.append(theme)
        return merged

    @staticmethod
    def _is_theme_name(name: str, category: str) -> bool:
        if not name:
            return False
        if category in {"concept", "industry"}:
            if re.fullmatch(r"\d{6}\.(?:SZ|SH|BJ)", name):
                return False
            if any(token in name for token in (".SZ", ".SH", ".BJ")):
                return False
            stock_suffixes = (
                "股份",
                "科技",
                "电气",
                "电子",
                "智能",
                "集团",
                "制造",
                "信息",
                "光电",
                "通信",
                "材料",
                "能源",
                "电源",
                "精密",
            )
            if name.endswith(stock_suffixes) and len(name) <= 6:
                return False
        return True

    @staticmethod
    def _collect_names(items: Iterable[RotationTheme]) -> list[str]:
        return [item.name for item in items]

    @staticmethod
    def _maybe_float(value: Any) -> float | None:
        try:
            return None if value is None else float(value)
        except Exception:
            return None

    @staticmethod
    def _maybe_int(value: Any) -> int | None:
        try:
            return None if value is None else int(value)
        except Exception:
            return None

    @staticmethod
    def _dedupe(items: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if not item or item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

