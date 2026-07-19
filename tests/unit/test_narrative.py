from __future__ import annotations

from datetime import date

from review.narrative import ReviewNarrative


def _payload() -> dict:
    return {
        "trade_date": "2026-05-19",
        "findings": [
            "当日涨停 90 家。",
            "市场宽度偏强，净广度 1834。",
            "主线确认：寒武纪。",
        ],
        "metrics": {
            "summary": {
                "limit_up": 90,
                "limit_down": 0,
                "breadth_net": 1834,
                "hot_concepts": ["寒武纪", "芯原股份", "东山精密"],
            },
            "rotation": {
                "main": [{"category": "concept", "name": "寒武纪"}],
                "secondary": [{"category": "industry", "name": "半导体"}],
                "active": [{"category": "concept", "name": "寒武纪"}],
                "failed": [{"category": "concept", "name": "德明利"}],
            },
            "risk_flags": ["炸板率偏高"],
            "raw_data": {
                "index_perf": {"000001.SH": {"pct_chg": 1.2}},
                "limit_stats": {"broken": 10, "broken_rate": 0.11},
                "top_industries_in": [{"industry_name": "半导体", "main_inflow": 123}],
                "top_industries_out": [{"industry_name": "银行", "main_inflow": -12}],
                "top_concepts_in": [{"concept_name": "寒武纪", "main_inflow": 456}],
                "top_concepts_out": [{"concept_name": "小金属", "main_inflow": -45}],
                "top_stocks_in": [{"name": "寒武纪", "ts_code": "688256.SH", "main_inflow": 999}],
                "top_stocks_out": [{"name": "宁德时代", "ts_code": "300750.SZ", "main_inflow": -666}],
                "hot_concepts": [{"concept_name": "寒武纪"}],
                "prev_hot_review": [{"concept_name": "电力", "verdict": "分化"}],
            },
        },
    }


def test_review_narrative_contains_required_sections():
    markdown = ReviewNarrative().render(_payload())

    required_sections = [
        "## 顶部摘要",
        "## 卡片区",
        "## 1. 一句话总收口",
        "## 2. 盘型/环境",
        "## 2.5 资金流证据",
        "## 2.6 情绪运行阶段",
        "## 3. 上一交易日重点轮动支线现状",
        "## 4. 主线/次主线/活口/失败轮动/资金撤退方向",
        "## 5. 次日策略提示",
        "## 6. 观察池",
    ]
    for section in required_sections:
        assert section in markdown


def test_review_narrative_exposes_cards_and_image_sections_in_payload():
    payload = ReviewNarrative().build_visual_payload(_payload(), date(2026, 5, 19))

    assert payload["header"]["title"] == "2026-05-19 正式复盘"
    assert len(payload["cards"]) == 4
    assert [section["title"] for section in payload["sections"]] == [
        "一句话总收口",
        "盘型/环境",
        "资金流证据",
        "情绪运行阶段",
        "上一交易日重点轮动支线现状",
        "主线 / 次主线 / 活口 / 失败轮动 / 资金撤退方向",
        "次日策略提示",
        "观察池",
        "风险提示",
    ]
