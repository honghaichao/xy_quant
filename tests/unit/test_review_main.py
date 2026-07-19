from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from review import main as review_main


@dataclass
class DummyAnalysis:
    trade_date: str = "2024-01-02"
    findings: list[str] | None = None
    metrics: dict | None = None

    def __post_init__(self) -> None:
        if self.findings is None:
            self.findings = ["ok"]
        if self.metrics is None:
            self.metrics = {"review_snapshot": {}}


def test_build_parser_has_required_args() -> None:
    parser = review_main.build_parser()
    args = parser.parse_args(["--trade-date", "2024-01-02"])
    assert args.trade_date == "2024-01-02"
    assert args.market_duckdb_path == review_main.DEFAULT_MARKET_DUCKDB_PATH
    assert args.output_dir == review_main.DEFAULT_OUTPUT_DIR


def test_run_daily_review_accepts_date_instance(monkeypatch, tmp_path: Path) -> None:
    class DummyCollector:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def collect(self, trade_date):
            assert trade_date.isoformat() == "2024-01-02"
            return DummyAnalysis().metrics

    class DummyAnalyzer:
        def analyze(self, snapshot):
            return DummyAnalysis()

    class DummyNarrative:
        def render(self, data, output_path=None):
            return "# report\n"

    monkeypatch.setattr(review_main, "ReviewCollector", DummyCollector)
    monkeypatch.setattr(review_main, "ReviewAnalyzer", lambda: DummyAnalyzer())
    monkeypatch.setattr(review_main, "ReviewNarrative", lambda: DummyNarrative())
    monkeypatch.setattr(review_main, "PROJECT_ROOT", Path("/tmp"))
    monkeypatch.setattr(review_main, "DEFAULT_MARKET_DUCKDB_PATH", tmp_path / "market.duckdb")
    monkeypatch.setattr(review_main, "DEFAULT_META_DB_PATH", tmp_path / "meta.duckdb")
    monkeypatch.setattr(review_main, "RECAP_DUCKDB_PATH", tmp_path / "market.duckdb")
    monkeypatch.setattr(
        review_main,
        "RecapData",
        lambda **kwargs: type("DummyRecap", (), {"_payload": kwargs})(),
    )
    real_asdict = review_main.asdict
    monkeypatch.setattr(
        review_main,
        "asdict",
        lambda obj: obj._payload if hasattr(obj, "_payload") else real_asdict(obj),
    )
    monkeypatch.setattr(review_main, "collect_minute_progress", lambda: {"completed_count": 1})
    monkeypatch.setattr(review_main, "collect_duckdb_stats", lambda: {"minute_bar_rows": 10})
    monkeypatch.setattr(review_main, "collect_postgres_stats", lambda: {"public_table_count": 2})
    monkeypatch.setattr(review_main, "collect_scheduler_snapshot", lambda: {"exists": True})

    output_path = review_main.run_daily_review(
        trade_date=date(2024, 1, 2),
        output_dir=tmp_path / "review",
    )

    assert output_path.exists()


def test_run_daily_review_writes_real_report_payload(monkeypatch, tmp_path: Path) -> None:
    class DummyCollector:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def collect(self, trade_date):
            return DummyAnalysis().metrics

    class DummyAnalyzer:
        def analyze(self, snapshot):
            return DummyAnalysis()

    class DummyNarrative:
        def render(self, data, output_path=None):
            assert data["metrics"]["recap_data"]["plan_path"] == "/tmp/PLAN.md"
            assert data["metrics"]["review_snapshot"]["trade_date"] == "2024-01-02"
            assert "p1_actual_indicator_chain" not in data["metrics"]
            return "# report\n"

    monkeypatch.setattr(review_main, "ReviewCollector", DummyCollector)
    monkeypatch.setattr(review_main, "ReviewAnalyzer", lambda: DummyAnalyzer())
    monkeypatch.setattr(review_main, "ReviewNarrative", lambda: DummyNarrative())
    monkeypatch.setattr(review_main, "PROJECT_ROOT", Path("/tmp"))
    monkeypatch.setattr(review_main, "DEFAULT_MARKET_DUCKDB_PATH", tmp_path / "market.duckdb")
    monkeypatch.setattr(review_main, "DEFAULT_META_DB_PATH", tmp_path / "meta.duckdb")
    monkeypatch.setattr(review_main, "RECAP_DUCKDB_PATH", tmp_path / "market.duckdb")
    monkeypatch.setattr(
        review_main,
        "RecapData",
        lambda **kwargs: type("DummyRecap", (), {"_payload": kwargs})(),
    )
    real_asdict = review_main.asdict
    monkeypatch.setattr(
        review_main,
        "asdict",
        lambda obj: obj._payload if hasattr(obj, "_payload") else real_asdict(obj),
    )
    monkeypatch.setattr(review_main, "collect_minute_progress", lambda: {"completed_count": 1})
    monkeypatch.setattr(review_main, "collect_duckdb_stats", lambda: {"minute_bar_rows": 10})
    monkeypatch.setattr(review_main, "collect_postgres_stats", lambda: {"public_table_count": 2})
    monkeypatch.setattr(review_main, "collect_scheduler_snapshot", lambda: {"exists": True})
    monkeypatch.setattr(
        review_main,
        "build_report",
        lambda start_date, end_date: {"total_trade_days": 1, "market": [], "meta": []},
    )

    output_path = review_main.run_daily_review(
        trade_date="2024-01-02",
        output_dir=tmp_path / "review",
    )

    assert output_path.exists()
    assert output_path.name == "review_2024-01-02.md"


def test_main_writes_report_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        review_main,
        "run_daily_review",
        lambda **kwargs: tmp_path / "review" / "review_2024-01-02.md",
    )
    monkeypatch.setattr(
        review_main.sys,
        "argv",
        ["review-main", "--trade-date", "2024-01-02", "--output-dir", str(tmp_path / "review")],
    )

    assert review_main.main() == 0


def test_build_meta_store_prefers_duckdb_when_meta_file_exists(tmp_path: Path) -> None:
    meta_path = tmp_path / "meta.duckdb"
    meta_path.write_text("stub", encoding="utf-8")

    store = review_main._build_meta_store(meta_path)

    assert isinstance(store, review_main.DuckDBQueryStore)


def test_build_meta_store_falls_back_to_postgres(monkeypatch, tmp_path: Path) -> None:
    sentinel = object()
    monkeypatch.setattr(review_main, "PostgresQueryStore", lambda: sentinel)

    store = review_main._build_meta_store(tmp_path / "missing_meta.duckdb")

    assert store is sentinel


def test_run_daily_review_closes_postgres_meta_store(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []

    class DummyStore:
        def close(self) -> None:
            events.append("closed")

    class DummyCollector:
        def __init__(self, *_, **kwargs) -> None:
            self._meta_store = kwargs["meta_store"]

        def collect(self, trade_date):
            return DummyAnalysis().metrics

    class DummyAnalyzer:
        def analyze(self, snapshot):
            return DummyAnalysis()

    class DummyNarrative:
        def render(self, data, output_path=None):
            return "# report\n"

    monkeypatch.setattr(review_main, "_build_meta_store", lambda _path: DummyStore())
    monkeypatch.setattr(review_main, "ReviewCollector", DummyCollector)
    monkeypatch.setattr(review_main, "ReviewAnalyzer", lambda: DummyAnalyzer())
    monkeypatch.setattr(review_main, "ReviewNarrative", lambda: DummyNarrative())
    monkeypatch.setattr(review_main, "PROJECT_ROOT", Path("/tmp"))
    monkeypatch.setattr(review_main, "DEFAULT_MARKET_DUCKDB_PATH", tmp_path / "market.duckdb")
    monkeypatch.setattr(review_main, "DEFAULT_META_DB_PATH", tmp_path / "meta.duckdb")
    monkeypatch.setattr(review_main, "RECAP_DUCKDB_PATH", tmp_path / "market.duckdb")
    monkeypatch.setattr(
        review_main,
        "RecapData",
        lambda **kwargs: type("DummyRecap", (), {"_payload": kwargs})(),
    )
    real_asdict = review_main.asdict
    monkeypatch.setattr(
        review_main,
        "asdict",
        lambda obj: obj._payload if hasattr(obj, "_payload") else real_asdict(obj),
    )
    monkeypatch.setattr(review_main, "collect_minute_progress", lambda: {"completed_count": 1})
    monkeypatch.setattr(review_main, "collect_duckdb_stats", lambda: {"minute_bar_rows": 10})
    monkeypatch.setattr(review_main, "collect_postgres_stats", lambda: {"public_table_count": 2})
    monkeypatch.setattr(review_main, "collect_scheduler_snapshot", lambda: {"exists": True})
    monkeypatch.setattr(
        review_main,
        "build_report",
        lambda start_date, end_date: {"total_trade_days": 1, "market": [], "meta": []},
    )

    review_main.run_daily_review(
        trade_date="2024-01-02",
        output_dir=tmp_path / "review",
    )

    assert events == ["closed"]


def test_run_daily_review_fails_when_image_rendering_dependency_missing(monkeypatch, tmp_path: Path) -> None:
    class DummyCollector:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def collect(self, trade_date):
            return DummyAnalysis().metrics

    class DummyAnalyzer:
        def analyze(self, snapshot):
            return DummyAnalysis()

    class FailingNarrative:
        def render(self, data, output_path=None):
            raise RuntimeError("Pillow is required to render review images")

    monkeypatch.setattr(review_main, "ReviewCollector", DummyCollector)
    monkeypatch.setattr(review_main, "ReviewAnalyzer", lambda: DummyAnalyzer())
    monkeypatch.setattr(review_main, "ReviewNarrative", lambda: FailingNarrative())
    monkeypatch.setattr(review_main, "PROJECT_ROOT", Path("/tmp"))
    monkeypatch.setattr(review_main, "DEFAULT_MARKET_DUCKDB_PATH", tmp_path / "market.duckdb")
    monkeypatch.setattr(review_main, "DEFAULT_META_DB_PATH", tmp_path / "meta.duckdb")
    monkeypatch.setattr(review_main, "RECAP_DUCKDB_PATH", tmp_path / "market.duckdb")
    monkeypatch.setattr(
        review_main,
        "RecapData",
        lambda **kwargs: type("DummyRecap", (), {"_payload": kwargs})(),
    )
    real_asdict = review_main.asdict
    monkeypatch.setattr(
        review_main,
        "asdict",
        lambda obj: obj._payload if hasattr(obj, "_payload") else real_asdict(obj),
    )
    monkeypatch.setattr(review_main, "collect_minute_progress", lambda: {"completed_count": 1})
    monkeypatch.setattr(review_main, "collect_duckdb_stats", lambda: {"minute_bar_rows": 10})
    monkeypatch.setattr(review_main, "collect_postgres_stats", lambda: {"public_table_count": 2})
    monkeypatch.setattr(review_main, "collect_scheduler_snapshot", lambda: {"exists": True})
    monkeypatch.setattr(
        review_main,
        "build_report",
        lambda start_date, end_date: {"total_trade_days": 1, "market": [], "meta": []},
    )

    with pytest.raises(RuntimeError, match="Pillow is required"):
        review_main.run_daily_review(
            trade_date="2024-01-02",
            output_dir=tmp_path / "review",
        )
