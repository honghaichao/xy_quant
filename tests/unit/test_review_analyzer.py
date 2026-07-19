from __future__ import annotations

from datetime import date

import pandas as pd

from review.analyzer import ReviewAnalyzer
from review.collector import ReviewRawData


def _build_raw_data() -> ReviewRawData:
    return ReviewRawData(
        trade_date=date(2024, 1, 2),
        index_perf={"000001.SH": {"close": 3000.0, "pct_chg": 1.2}},
        breadth={"up": 3200, "down": 1400, "flat": 200, "net": 1800},
        limit_stats={"limit_up": 62, "limit_down": 3, "broken": 12, "broken_rate": 12 / 62},
        limit_up_details=pd.DataFrame(),
        consecutive_limits=[{"limit_times": 3, "stocks": [{"ts_code": "000001.SZ", "name": "龙一", "amount": 10.0}]}],
        top_industries_in=[
            {"industry_name": "半导体", "net_amount": 162.0, "pct_chg": 3.1, "limit_count": 14},
            {"industry_name": "通信设备", "net_amount": 68.0, "pct_chg": 2.2, "limit_count": 5},
        ],
        top_industries_out=[
            {"industry_name": "电力", "net_amount": -74.0, "pct_chg": -1.3, "limit_count": 0},
        ],
        top_concepts_in=[
            {"concept_name": "算力", "net_amount": 88.0, "pct_chg": 4.1, "limit_count": 8},
            {"concept_name": "机器人", "net_amount": 52.0, "pct_chg": 3.2, "limit_count": 6},
        ],
        top_concepts_out=[
            {"concept_name": "燃气", "net_amount": -42.0, "pct_chg": -2.1, "limit_count": 0},
        ],
        top_stocks_in=[
            {"name": "中际旭创", "net_amount": 18.0, "pct_chg": 6.6, "limit_times": 1},
            {"name": "新易盛", "net_amount": 16.0, "pct_chg": 5.3, "limit_times": 1},
        ],
        top_stocks_out=[
            {"name": "某电力股", "net_amount": -11.0, "pct_chg": -4.4, "limit_times": 0},
        ],
        hot_concepts=[
            {"concept_code": "C1", "concept_name": "算力", "main_inflow": 88.0, "pct_chg": 4.1, "limit_count": 8, "net_amount": 88.0},
            {"concept_code": "C2", "concept_name": "机器人", "main_inflow": 52.0, "pct_chg": 3.2, "limit_count": 6, "net_amount": 52.0},
            {"concept_code": "C3", "concept_name": "液冷", "main_inflow": 21.0, "pct_chg": 2.4, "limit_count": 2, "net_amount": 21.0},
        ],
        prev_hot_review=[
            {"concept_code": "P1", "concept_name": "商业航天", "verdict": "分化"},
        ],
    )


def test_analyzer_emits_rotation_structure_and_watchlist() -> None:
    analysis = ReviewAnalyzer().analyze(_build_raw_data())

    rotation = analysis.metrics["rotation"]
    assert rotation["main"][0]["name"] == "算力"
    assert rotation["main"][1]["name"] == "机器人"
    assert rotation["secondary"][0]["name"] == "半导体"
    assert rotation["failed"][0]["name"] == "燃气"
    assert analysis.metrics["watchlist"][:3] == ["算力", "机器人", "半导体"]


def test_analyzer_emits_rich_findings_and_risk_flags() -> None:
    analysis = ReviewAnalyzer().analyze(_build_raw_data())

    assert any("主线确认" in finding for finding in analysis.findings)
    assert any("活口观察" in finding for finding in analysis.findings)
    assert any("失败轮动" in finding for finding in analysis.findings)
    assert analysis.metrics["risk_flags"] == []
