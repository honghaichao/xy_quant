from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from review.renderer import image_renderer


@pytest.fixture
def sample_payload() -> dict[str, object]:
    return {
        "trade_date": "2024-01-02",
        "findings": [
            "当日涨停 62 家。",
            "主线确认：算力 / 机器人 / 半导体。",
            "活口观察：算力 / 机器人 / 液冷。",
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
                "main": [{"name": "算力", "net_amount": 88.0}, {"name": "机器人", "net_amount": 52.0}],
                "secondary": [{"name": "半导体", "net_amount": 162.0}, {"name": "通信设备", "net_amount": 68.0}],
                "active": [{"name": "算力", "net_amount": 88.0}, {"name": "液冷", "net_amount": 21.0}],
                "failed": [{"name": "燃气", "net_amount": -42.0}, {"name": "电力", "net_amount": -74.0}],
            },
            "watchlist": ["算力", "机器人", "半导体", "通信设备"],
            "risk_flags": [],
            "p1_actual_indicator_chain": {
                "total_trade_days": 1,
                "sh_index": "+0.11%",
                "sz_index": "-0.09%",
                "turnover": "520.29亿",
                "advancers": "2746",
                "decliners": "2339",
                "flat": "124",
            },
        },
    }


def test_render_review_image_raises_when_pillow_unavailable(monkeypatch, tmp_path: Path, sample_payload: dict[str, object]) -> None:
    monkeypatch.setattr(image_renderer, "Image", None)
    monkeypatch.setattr(image_renderer, "ImageDraw", None)
    monkeypatch.setattr(image_renderer, "ImageFont", None)

    with pytest.raises(RuntimeError, match="Pillow is required"):
        image_renderer.render_review_image(sample_payload, tmp_path, date(2024, 1, 2))

    assert not (tmp_path / "review_2024-01-02.png").exists()


def test_render_review_image_writes_valid_png(tmp_path: Path, sample_payload: dict[str, object]) -> None:
    pillow = pytest.importorskip("PIL.Image")

    output_path = image_renderer.render_review_image(sample_payload, tmp_path, date(2024, 1, 2))

    assert output_path.exists()
    assert output_path.stat().st_size > 8
    with pillow.open(output_path) as img:
        assert img.format == "PNG"
        assert img.size[0] == image_renderer.CANVAS_WIDTH
        assert img.size[1] > 1200


def test_render_review_image_uses_high_resolution_downsample(tmp_path: Path, sample_payload: dict[str, object]) -> None:
    pytest.importorskip("PIL.Image")

    output_path = image_renderer.render_review_image(sample_payload, tmp_path, date(2024, 1, 2))

    assert output_path.exists()
    assert image_renderer.RENDER_SCALE >= 2
