from __future__ import annotations

from pathlib import Path

from review.narrative import ReviewNarrative


def _payload() -> dict[str, object]:
    return {
        "trade_date": "2024-01-02",
        "findings": [
            "当日涨停 62 家。",
            "主线确认：算力 / 机器人 / 半导体。",
            "活口观察：算力 / 机器人 / 液冷。",
            "失败轮动：燃气 / 电力。",
        ],
        "metrics": {
            "summary": {
                "limit_up": 62,
                "limit_down": 3,
                "breadth_net": 1800,
                "hot_concepts": ["算力", "机器人", "液冷"],
                "north_net_amount": 37.5,
            },
            "rotation": {
                "main": [{"name": "算力", "net_amount": 88.0, "category": "concept"}, {"name": "机器人", "net_amount": 52.0, "category": "concept"}],
                "secondary": [{"name": "半导体", "net_amount": 162.0, "category": "concept"}, {"name": "通信设备", "net_amount": 68.0, "category": "industry"}],
                "active": [{"name": "算力", "net_amount": 88.0, "category": "concept"}, {"name": "液冷", "net_amount": 21.0, "category": "concept"}],
                "failed": [{"name": "燃气", "net_amount": -42.0, "category": "industry"}, {"name": "电力", "net_amount": -74.0, "category": "industry"}],
            },
            "watchlist": ["算力", "机器人", "半导体", "通信设备"],
            "risk_flags": [],
            "review_snapshot": {"trade_date": "2024-01-02", "market_duckdb_path": "/tmp/market.duckdb", "output_dir": "/tmp/out"},
            "recap_data": {
                "plan_path": "/tmp/PLAN.md",
                "duckdb_path": "/tmp/market.duckdb",
                "minute_progress": {"completed_count": 1},
                "duckdb_stats": {"tables": 1},
                "postgres_stats": {"tables": 2},
                "scheduler_snapshot": {"jobs": 3},
            },
            "p1_actual_indicator_chain": {"total_trade_days": 1, "market": ["x"], "meta": ["y"]},
        },
    }


def test_render_contains_structured_report_sections() -> None:
    rendered = ReviewNarrative().render(_payload(), None)

    assert "# 2024-01-02 正式复盘" in rendered
    assert "## 顶部摘要" in rendered
    assert "## 卡片区" in rendered
    assert "### 主线" in rendered
    assert "### 次主线" in rendered
    assert "### 风险边界" in rendered
    assert "## 1. 一句话总收口" in rendered
    assert "## 2. 盘型/环境" in rendered
    assert "## 2.5 资金流证据" in rendered
    assert "## 2.6 情绪运行阶段" in rendered
    assert "## 3. 上一交易日重点轮动支线现状" in rendered
    assert "## 4. 主线/次主线/活口/失败轮动/资金撤退方向" in rendered
    assert "主线：算力、机器人" in rendered
    assert "次主线：半导体、通信设备" in rendered
    assert "风险边界：暂无新增高危风险项，仍以分歧中的主线确认节奏为主。" in rendered
    assert "一句话总收口" in rendered
    assert "市场环境：涨停 62 家（口径：排除 ST、北交所），跌停 3 家（口径：排除 ST、北交所），市场净广度 1800。" in rendered
    assert "行业流入 TOP3" in rendered
    assert "个股流出 TOP5" in rendered
    assert "情绪阶段：" in rendered
    assert "昨日强势板块今日表现回顾" in rendered
    assert "资金撤退方向" in rendered
    assert "个股池：无" in rendered
    assert "北向资金" not in rendered
    assert "P1 覆盖报告" not in rendered
    assert "coverage chart" not in rendered
    assert "total_trade_days" not in rendered
    assert "/tmp/market.duckdb" not in rendered
    assert "/tmp/PLAN.md" not in rendered


def test_render_filters_code_like_secondary_and_stock_like_main_names() -> None:
    payload = _payload()
    payload["findings"] = [
        "主线确认：芯原股份 / 半导体。",
        "活口观察：长江电力 / 半导体。",
        "失败轮动：中际旭创 / 电力。",
        "热点概念包括：算力, 机器人, 液冷。",
    ]
    payload["metrics"]["rotation"]["main"] = [
        {"name": "芯原股份", "net_amount": 100.0, "category": "concept"},
        {"name": "半导体", "net_amount": 80.0, "category": "concept"},
    ]
    payload["metrics"]["rotation"]["secondary"] = [
        {"name": "002131.SZ", "net_amount": 50.0, "category": "concept"},
        {"name": "电力", "net_amount": 40.0, "category": "industry"},
        {"name": "阳光电源", "net_amount": 38.0, "category": "concept"},
    ]
    payload["metrics"]["rotation"]["active"] = [
        {"name": "长江电力", "net_amount": 70.0, "category": "stock"},
        {"name": "半导体", "net_amount": 60.0, "category": "concept"},
    ]
    payload["metrics"]["rotation"]["failed"] = [
        {"name": "中际旭创", "net_amount": -50.0, "category": "stock"},
        {"name": "电力", "net_amount": -20.0, "category": "industry"},
    ]
    payload["metrics"]["summary"]["hot_concepts"] = ["芯原股份", "长江电力", "光迅科技"]

    analyzed_payload = {
        **payload,
        "metrics": {
            **payload["metrics"],
            "summary": {k: v for k, v in payload["metrics"]["summary"].items() if k != "north_net_amount"},
        },
    }

    rendered = ReviewNarrative().render(analyzed_payload, None)

    assert "主线：半导体" in rendered
    assert "芯原股份" not in rendered.split("### 主线", 1)[1].split("### 次主线", 1)[0]
    assert "次主线：电力" in rendered
    assert "002131.SZ" not in rendered
    assert "阳光电源" not in rendered
    assert "长江电力" not in rendered.split("## 6. 观察池", 1)[1]
    assert "中际旭创" not in rendered.split("## 6. 观察池", 1)[1]
    assert "芯原股份" not in rendered
    assert "光迅科技" not in rendered
    assert "活口：半导体" in rendered
    assert "失败轮动：电力" in rendered
    assert "方向池：半导体、电力" in rendered
    assert "次日策略提示：" in rendered
    assert "半导体" in rendered.split("次日策略提示：", 1)[1]
    assert "长江电力" not in rendered.split("次日策略提示：", 1)[1]


def test_render_calls_image_renderer_when_output_path_provided(monkeypatch, tmp_path: Path) -> None:
    output_path = tmp_path / "review_2024-01-02.md"
    calls: list[tuple[dict[str, object], Path, object]] = []

    def fake_render_review_image(data, output_dir, trade_day):
        calls.append((data, output_dir, trade_day))
        png = output_dir / "review_2024-01-02.png"
        png.write_bytes(b"png")
        return png

    monkeypatch.setattr("review.narrative.render_review_image", fake_render_review_image)

    rendered = ReviewNarrative().render(_payload(), output_path)

    assert output_path.parent.joinpath("review_2024-01-02.png").exists()
    assert calls and calls[0][1] == output_path.parent
    assert rendered.startswith("# 2024-01-02 正式复盘")
