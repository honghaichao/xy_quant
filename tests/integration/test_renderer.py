from __future__ import annotations

from datetime import date
from pathlib import Path

from review.narrative import ReviewNarrative
from review.renderer.html_renderer import HtmlRenderer
from review.renderer.image_renderer import render_review_image


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


def test_html_renderer_outputs_plan_style_markup(tmp_path: Path):
    visual = ReviewNarrative().build_visual_payload(_payload(), date(2026, 5, 19))
    output = tmp_path / "review.html"

    HtmlRenderer().render(visual, output)
    html = output.read_text(encoding="utf-8")

    assert "linear-gradient" in html
    assert "summary-grid" in html
    assert "section-bar" in html
    assert "2026-05-19 正式复盘" in html


def test_render_review_image_produces_png(tmp_path: Path):
    output = render_review_image(_payload(), tmp_path, date(2026, 5, 19))

    assert output.exists()
    assert output.suffix == ".png"
