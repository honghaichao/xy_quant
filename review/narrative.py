from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from interfaces.report_renderer import IReportRenderer


class ReviewNarrative(IReportRenderer):
    def render(self, data: dict[str, Any], output_path: Path | None = None) -> str:
        trade_day = str(data.get("trade_date", "unknown"))
        visual = self.build_visual_payload(data, date.fromisoformat(trade_day))

        md = [f"# {trade_day} 正式复盘", "", "## 顶部摘要", visual["header"]["summary"], ""]
        findings = [item for item in visual["header"].get("findings", []) if item]
        if findings:
            md.extend(["## 今日结论", *findings, ""])

        md.extend([
            "## 卡片区",
            *[f"- {card['label']}：{card['value']}（{card['note']}）" for card in visual["cards"]],
            "",
        ])

        for section in visual["sections"]:
            index = section['index']
            separator = '' if '.' in index else '.'
            md.append(f"## {index}{separator} {section['title'].replace(' / ', '/')}")
            md.extend(section["lines"])
            md.append("")

        return "\n".join(md).strip() + "\n"

    def build_visual_payload(self, data: dict[str, Any], trade_day: date) -> dict[str, Any]:
        metrics = data.get("metrics", {})
        summary = metrics.get("summary", {})
        rotation = metrics.get("rotation", {})
        risk_flags = metrics.get("risk_flags", [])
        raw_data = metrics.get("raw_data", {})

        top_industries_in = raw_data.get("top_industries_in", [])
        top_industries_out = raw_data.get("top_industries_out", [])
        top_concepts_in = raw_data.get("top_concepts_in", [])
        top_concepts_out = raw_data.get("top_concepts_out", [])
        top_stocks_in = raw_data.get("top_stocks_in", [])
        top_stocks_out = raw_data.get("top_stocks_out", [])
        prev_hot_review = raw_data.get("prev_hot_review", [])

        main_items = self._filter_theme_items(rotation.get("main", []))
        secondary_items = self._filter_theme_items(rotation.get("secondary", []))
        active_items = self._filter_theme_items(rotation.get("active", []))
        failed_items = self._filter_theme_items(rotation.get("failed", []))
        direction_watchlist = self._theme_watchlist(rotation, limit=6)
        stock_watchlist = self._stock_watchlist(raw_data, limit=6)
        findings = self._sanitize_findings(data.get("findings", []), rotation)
        top_summary = self._build_top_summary(data.get("findings", []), summary, rotation)
        risk_boundary = self._risk_boundary_text(risk_flags)
        mood_stage = self._infer_emotion_stage(summary, risk_flags, rotation)
        next_day_hint = self._next_day_hint(summary, risk_flags, rotation)
        capital_evidence = [
            f"行业流入 TOP3：{self._format_top_items(top_industries_in[:3])}",
            f"行业流出 TOP3：{self._format_top_items(top_industries_out[:3])}",
            f"板块流入 TOP3：{self._format_top_items(top_concepts_in[:3])}",
            f"板块流出 TOP3：{self._format_top_items(top_concepts_out[:3])}",
            f"个股流入 TOP5：{self._format_top_items(top_stocks_in[:5])}",
            f"个股流出 TOP5：{self._format_top_items(top_stocks_out[:5])}",
        ]

        sections = [
            {
                "index": "1",
                "title": "一句话总收口",
                "lines": [f"一句话总收口：{top_summary}"],
            },
            {
                "index": "2",
                "title": "盘型/环境",
                "lines": [
                    (
                        "市场环境："
                        f"涨停 {summary.get('limit_up', 0)} 家（口径：排除 ST、北交所），"
                        f"跌停 {summary.get('limit_down', 0)} 家（口径：排除 ST、北交所），"
                        f"市场净广度 {summary.get('breadth_net', 0)}。"
                    ),
                    f"指数表现：{self._format_index_perf(raw_data.get('index_perf', {}))}",
                    f"炸板情况：{self._format_broken_rate(raw_data.get('limit_stats', {}))}",
                ],
            },
            {
                "index": "2.5",
                "title": "资金流证据",
                "lines": capital_evidence,
            },
            {
                "index": "2.6",
                "title": "情绪运行阶段",
                "lines": [
                    f"情绪阶段：{mood_stage}",
                    f"证据：{self._build_stage_evidence(summary, risk_flags, rotation)}",
                ],
            },
            {
                "index": "3",
                "title": "上一交易日重点轮动支线现状",
                "lines": [f"昨日强势板块今日表现回顾：{self._format_prev_hot_review(prev_hot_review)}"],
            },
            {
                "index": "4",
                "title": "主线 / 次主线 / 活口 / 失败轮动 / 资金撤退方向",
                "lines": [
                    f"主线：{self._join_theme_names(main_items)}",
                    f"次主线：{self._join_theme_names(secondary_items)}",
                    f"活口：{self._join_theme_names(active_items)}",
                    f"失败轮动：{self._join_theme_names(failed_items)}",
                    f"资金撤退方向：{self._format_top_items(top_concepts_out[:5] or top_industries_out[:5] or top_stocks_out[:5])}",
                    f"风险边界：{risk_boundary}",
                ],
            },
            {
                "index": "5",
                "title": "次日策略提示",
                "lines": [f"次日策略提示：{next_day_hint}"],
            },
            {
                "index": "6",
                "title": "观察池",
                "lines": [
                    f"方向池：{self._join_names(direction_watchlist)}",
                    f"个股池：{self._join_names(stock_watchlist)}",
                ],
            },
            {
                "index": "7",
                "title": "风险提示",
                "lines": [*([f"风险提示：{flag}" for flag in risk_flags] or ["风险提示：暂无新增高危风险项。"])],
            },
        ]

        cards = [
            {"label": "主线", "value": self._join_theme_names(main_items), "note": f"活口：{self._join_theme_names(active_items)}"},
            {"label": "次主线", "value": self._join_theme_names(secondary_items), "note": f"失败轮动：{self._join_theme_names(failed_items)}"},
            {"label": "情绪阶段", "value": mood_stage, "note": f"风险边界：{risk_boundary}"},
            {"label": "资金流证据", "value": self._format_top_items(top_concepts_in[:3] or top_industries_in[:3] or top_stocks_in[:3]), "note": f"撤退方向：{self._format_top_items(top_concepts_out[:3] or top_industries_out[:3] or top_stocks_out[:3])}"},
        ]

        return {
            "trade_date": trade_day.isoformat(),
            "header": {
                "title": f"{trade_day.isoformat()} 正式复盘",
                "subtitle": "适合微信/飞书分享的财经复盘长图",
                "summary": top_summary,
                "findings": findings,
            },
            "cards": cards,
            "sections": sections,
        }

    @staticmethod
    def _build_top_summary(findings: list[str], summary: dict[str, Any], rotation: dict[str, Any]) -> str:
        sanitized = ReviewNarrative._sanitize_findings(findings, rotation)
        if sanitized:
            return sanitized[0]
        return (
            f"主线聚焦{ReviewNarrative._join_theme_names(ReviewNarrative._filter_theme_items(rotation.get('main', [])))}，"
            f"市场净广度{summary.get('breadth_net', 0)}。"
        )

    @staticmethod
    def _sanitize_findings(findings: list[str], rotation: dict[str, Any]) -> list[str]:
        if not findings:
            return []
        main_names = ReviewNarrative._join_theme_names(
            [item for item in rotation.get("main", []) if str(item.get("category", "")) in {"concept", "industry"}][:3]
        )
        active_names = ReviewNarrative._join_theme_names(ReviewNarrative._filter_theme_items(rotation.get("active", []))[:3])
        failed_names = ReviewNarrative._join_theme_names(ReviewNarrative._filter_theme_items(rotation.get("failed", []))[:3])
        hot_names = ReviewNarrative._join_names(ReviewNarrative._theme_watchlist(rotation, limit=3))
        sanitized: list[str] = []
        for finding in findings:
            text = str(finding)
            if text.startswith("主线确认："):
                sanitized.append(f"主线确认：{main_names}。")
            elif text.startswith("活口观察："):
                sanitized.append(f"活口：{active_names}。")
            elif text.startswith("失败轮动："):
                sanitized.append(f"失败轮动：{failed_names}。")
            elif text.startswith("热点概念包括："):
                sanitized.append(f"热点概念包括：{hot_names or '无'}。")
            else:
                sanitized.append(text)
        return sanitized

    @staticmethod
    def _risk_boundary_text(risk_flags: list[str]) -> str:
        if risk_flags:
            return "；".join(str(flag) for flag in risk_flags)
        return "暂无新增高危风险项，仍以分歧中的主线确认节奏为主。"

    @staticmethod
    def _infer_emotion_stage(summary: dict[str, Any], risk_flags: list[str], rotation: dict[str, Any]) -> str:
        breadth_net = float(summary.get("breadth_net", 0) or 0)
        limit_up = int(summary.get("limit_up", 0) or 0)
        limit_down = int(summary.get("limit_down", 0) or 0)
        if breadth_net < 0 or limit_down > limit_up:
            return "退潮"
        if "炸板率偏高" in risk_flags:
            return "分歧"
        if limit_up >= 60 and breadth_net > 1000 and rotation.get("main"):
            return "扩散"
        if rotation.get("main"):
            return "修复"
        return "冰点"

    @staticmethod
    def _build_stage_evidence(summary: dict[str, Any], risk_flags: list[str], rotation: dict[str, Any]) -> str:
        evidence = [
            f"涨停 {summary.get('limit_up', 0)} 家",
            f"跌停 {summary.get('limit_down', 0)} 家",
            f"净广度 {summary.get('breadth_net', 0)}",
        ]
        if rotation.get("main"):
            evidence.append(f"主线 {ReviewNarrative._join_theme_names(ReviewNarrative._filter_theme_items(rotation.get('main', [])[:3]))}")
        if risk_flags:
            evidence.append("风险信号：" + "；".join(str(flag) for flag in risk_flags))
        return "，".join(evidence)

    @staticmethod
    def _format_index_perf(index_perf: dict[str, dict[str, Any]]) -> str:
        if not index_perf:
            return "无"
        return "；".join(f"{ts_code} {metrics.get('pct_chg', 0)}%" for ts_code, metrics in index_perf.items())

    @staticmethod
    def _format_broken_rate(limit_stats: dict[str, Any]) -> str:
        broken = limit_stats.get("broken", 0)
        broken_rate = float(limit_stats.get("broken_rate", 0) or 0)
        return f"炸板 {broken} 家，炸板率 {broken_rate:.2%}"

    @staticmethod
    def _format_top_items(items: list[dict[str, Any]]) -> str:
        if not items:
            return "无"
        formatted: list[str] = []
        for item in items:
            name = str(item.get("concept_name") or item.get("industry_name") or item.get("name") or item.get("ts_code") or "")
            amount = item.get("main_inflow")
            if amount is None:
                amount = item.get("net_amount")
            if amount is None:
                amount = item.get("amount")
            pct_chg = item.get("pct_chg")
            part = name
            if amount is not None:
                part += f"({amount})"
            if pct_chg is not None:
                part += f"/{pct_chg}%"
            formatted.append(part)
        return "、".join(formatted)

    @staticmethod
    def _format_prev_hot_review(items: list[dict[str, Any]]) -> str:
        if not items:
            return "无"
        formatted = []
        for item in items[:10]:
            concept_name = item.get("concept_name") or item.get("name") or item.get("concept_code")
            verdict = item.get("verdict") or "待定"
            current_main_inflow = item.get("current_main_inflow")
            if current_main_inflow is None:
                formatted.append(f"{concept_name}({verdict})")
            else:
                formatted.append(f"{concept_name}({verdict}, 当日流入 {current_main_inflow})")
        return "、".join(str(part) for part in formatted)

    @staticmethod
    def _filter_theme_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [item for item in items if str(item.get("category", "")) in {"concept", "industry"}]

    @staticmethod
    def _theme_watchlist(rotation: dict[str, Any], limit: int = 6) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for key in ("main", "secondary", "active", "failed"):
            for item in rotation.get(key, []):
                name = str(item.get("name", ""))
                category = str(item.get("category", ""))
                if category not in {"concept", "industry"}:
                    continue
                if not ReviewNarrative._is_display_theme_name(name) or name in seen:
                    continue
                seen.add(name)
                ordered.append(name)
                if len(ordered) >= limit:
                    return ordered
        return ordered

    @staticmethod
    def _stock_watchlist(raw_data: dict[str, Any], limit: int = 6) -> list[str]:
        picks: list[str] = []
        seen: set[str] = set()
        for group_name in ("top_stocks_in", "top_stocks_out"):
            for item in raw_data.get(group_name, []):
                name = str(item.get("name") or item.get("ts_code") or "")
                if not name or name in seen:
                    continue
                seen.add(name)
                picks.append(name)
                if len(picks) >= limit:
                    return picks
        return picks

    @staticmethod
    def _next_day_hint(summary: dict[str, Any], risk_flags: list[str], rotation: dict[str, Any]) -> str:
        mainline = ReviewNarrative._join_theme_names(rotation.get("main", [])[:3])
        active = ReviewNarrative._join_theme_names(
            [item for item in rotation.get("active", []) if str(item.get("category", "")) in {"concept", "industry"}][:3]
        )
        breadth_net = float(summary.get("breadth_net", 0) or 0)
        if "炸板率偏高" in risk_flags:
            return f"优先盯住 {mainline} 的分歧转强确认，低位新发酵方向只做跟踪，不追日内一致性过强的扩散。"
        if breadth_net > 1000:
            return f"盘面仍有扩散条件，优先跟踪 {mainline}，同时观察 {active} 是否承接成为新增活口。"
        return f"先看 {mainline} 的承接质量，若主线走弱，再观察 {active} 是否成为资金回流方向。"

    @staticmethod
    def _join_theme_names(items: list[dict[str, Any]]) -> str:
        names = [
            str(item.get("name", ""))
            for item in items
            if item.get("name") and ReviewNarrative._is_display_theme_name(str(item.get("name", "")))
        ]
        return "、".join(names) if names else "无"

    @staticmethod
    def _is_display_theme_name(name: str) -> bool:
        if not name:
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
    def _join_names(items: list[Any]) -> str:
        names = [str(item) for item in items if item]
        return "、".join(names) if names else "无"
