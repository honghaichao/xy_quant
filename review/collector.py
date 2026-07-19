"""P1 复盘数据收集器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


class QueryStore(Protocol):
    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame: ...


class EmptyQueryStore:
    """Fallback store used when a data source is unavailable."""

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        return pd.DataFrame()


@dataclass(slots=True)
class ReviewRawData:
    trade_date: date
    index_perf: dict[str, dict[str, Any]]
    breadth: dict[str, int]
    limit_stats: dict[str, Any]
    limit_up_details: pd.DataFrame
    consecutive_limits: list[dict[str, Any]]
    top_industries_in: list[dict[str, Any]]
    top_industries_out: list[dict[str, Any]]
    top_concepts_in: list[dict[str, Any]]
    top_concepts_out: list[dict[str, Any]]
    top_stocks_in: list[dict[str, Any]]
    top_stocks_out: list[dict[str, Any]]
    hot_concepts: list[dict[str, Any]]
    prev_hot_review: list[dict[str, Any]]


class ReviewCollector:
    def __init__(self, market_store: QueryStore, meta_store: QueryStore) -> None:
        self._market_store = market_store
        self._meta_store = meta_store

    def collect(self, trade_date: date) -> ReviewRawData:
        return ReviewRawData(
            trade_date=trade_date,
            index_perf=self._collect_index_perf(trade_date),
            breadth=self._collect_breadth(trade_date),
            limit_stats=self._collect_limit_stats(trade_date),
            limit_up_details=self._collect_limit_up_details(trade_date),
            consecutive_limits=self._collect_consecutive_limits(trade_date),
            top_industries_in=self._collect_top_industries_in(trade_date),
            top_industries_out=self._collect_top_industries_out(trade_date),
            top_concepts_in=self._collect_top_concepts_in(trade_date),
            top_concepts_out=self._collect_top_concepts_out(trade_date),
            top_stocks_in=self._collect_top_stocks_in(trade_date),
            top_stocks_out=self._collect_top_stocks_out(trade_date),
            hot_concepts=self._collect_hot_concepts(trade_date),
            prev_hot_review=self._collect_prev_hot_review(trade_date),
        )

    def _collect_index_perf(self, trade_date: date) -> dict[str, dict[str, Any]]:
        df = self._safe_query(
            self._market_store,
            """
            SELECT ts_code, close, pct_chg
            FROM index_daily
            WHERE trade_date = :trade_date
            ORDER BY ts_code
            """,
            {"trade_date": trade_date},
        )
        return {
            str(row.ts_code): {"close": row.close, "pct_chg": row.pct_chg}
            for row in df.itertuples(index=False)
        }

    def _collect_breadth(self, trade_date: date) -> dict[str, int]:
        df = self._safe_query(
            self._market_store,
            """
            SELECT
                SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) AS up,
                SUM(CASE WHEN pct_chg < 0 THEN 1 ELSE 0 END) AS down,
                SUM(CASE WHEN pct_chg = 0 THEN 1 ELSE 0 END) AS flat
            FROM daily_bar
            WHERE trade_date = :trade_date
            """,
            {"trade_date": trade_date},
        )
        if df.empty:
            return {"up": 0, "down": 0, "flat": 0, "net": 0}
        row = df.iloc[0]
        up = int((0 if pd.isna(row.get("up", 0)) else row.get("up", 0)) or 0)
        down = int((0 if pd.isna(row.get("down", 0)) else row.get("down", 0)) or 0)
        flat = int((0 if pd.isna(row.get("flat", 0)) else row.get("flat", 0)) or 0)
        return {"up": up, "down": down, "flat": flat, "net": up - down}

    def _collect_limit_stats(self, trade_date: date) -> dict[str, Any]:
        up = self._scalar_market(
            'SELECT COUNT(*) AS value FROM limit_list WHERE trade_date = :trade_date AND "limit" = \'U\'',
            trade_date,
        )
        down = self._scalar_market(
            'SELECT COUNT(*) AS value FROM limit_list WHERE trade_date = :trade_date AND "limit" = \'D\'',
            trade_date,
        )
        broken = self._scalar_market(
            'SELECT COUNT(*) AS value FROM limit_list WHERE trade_date = :trade_date AND "limit" = \'U\' AND open_times > 0',
            trade_date,
        )
        broken_rate = broken / up if up else 0.0
        return {"limit_up": up, "limit_down": down, "broken": broken, "broken_rate": broken_rate}

    def _collect_limit_up_details(self, trade_date: date) -> pd.DataFrame:
        return self._safe_query(
            self._market_store,
            """
            SELECT
                trade_date, ts_code, name, close, pct_chg, amount, limit_amount,
                float_mv, total_mv, turnover_ratio, fd_amount, first_time, last_time,
                open_times, up_stat, limit_times, "limit"
            FROM limit_list
            WHERE trade_date = :trade_date AND "limit" = 'U'
            ORDER BY limit_times DESC, amount DESC
            """,
            {"trade_date": trade_date},
        )

    def _collect_consecutive_limits(self, trade_date: date) -> list[dict[str, Any]]:
        df = self._safe_query(
            self._market_store,
            """
            SELECT limit_times, ts_code, name, amount
            FROM limit_list
            WHERE trade_date = :trade_date AND "limit" = 'U' AND limit_times >= 2
            ORDER BY limit_times DESC, amount DESC
            """,
            {"trade_date": trade_date},
        )
        groups: dict[int, list[dict[str, Any]]] = {}
        for row in df.itertuples(index=False):
            groups.setdefault(int(row.limit_times), []).append(
                {"ts_code": row.ts_code, "name": row.name, "amount": row.amount}
            )
        return [
            {"limit_times": level, "stocks": stocks}
            for level, stocks in sorted(groups.items(), reverse=True)
        ]

    def _collect_top_industries_in(self, trade_date: date) -> list[dict[str, Any]]:
        return self._collect_money_flow_top(
            self._meta_store,
            table="industry_money_flow",
            name_field="industry_name",
            code_field="industry_code",
            trade_date=trade_date,
            asc=False,
        )

    def _collect_top_industries_out(self, trade_date: date) -> list[dict[str, Any]]:
        return self._collect_money_flow_top(
            self._meta_store,
            table="industry_money_flow",
            name_field="industry_name",
            code_field="industry_code",
            trade_date=trade_date,
            asc=True,
        )

    def _collect_top_concepts_in(self, trade_date: date) -> list[dict[str, Any]]:
        return self._collect_money_flow_top(
            self._meta_store,
            table="concept_money_flow",
            name_field="concept_name",
            code_field="concept_code",
            trade_date=trade_date,
            asc=False,
        )

    def _collect_top_concepts_out(self, trade_date: date) -> list[dict[str, Any]]:
        return self._collect_money_flow_top(
            self._meta_store,
            table="concept_money_flow",
            name_field="concept_name",
            code_field="concept_code",
            trade_date=trade_date,
            asc=True,
        )

    def _collect_top_stocks_in(self, trade_date: date) -> list[dict[str, Any]]:
        return self._collect_money_flow_top(
            self._meta_store,
            table="stock_money_flow",
            name_field="name",
            code_field="ts_code",
            trade_date=trade_date,
            asc=False,
        )

    def _collect_top_stocks_out(self, trade_date: date) -> list[dict[str, Any]]:
        return self._collect_money_flow_top(
            self._meta_store,
            table="stock_money_flow",
            name_field="name",
            code_field="ts_code",
            trade_date=trade_date,
            asc=True,
        )

    def _collect_hot_concepts(self, trade_date: date) -> list[dict[str, Any]]:
        df = self._safe_query(
            self._meta_store,
            """
            SELECT concept_code, concept_name, main_inflow, pct_chg, main_inflow_pct, super_inflow, big_inflow, mid_inflow, small_inflow
            FROM concept_money_flow
            WHERE trade_date = :trade_date
            ORDER BY main_inflow DESC NULLS LAST, pct_chg DESC NULLS LAST
            LIMIT 10
            """,
            {"trade_date": trade_date},
        )
        return [row._asdict() for row in df.itertuples(index=False)]

    def _collect_prev_hot_review(self, trade_date: date) -> list[dict[str, Any]]:
        prev_df = self._safe_query(
            self._meta_store,
            """
            SELECT MAX(trade_date) AS prev_trade_date
            FROM concept_money_flow
            WHERE trade_date < :trade_date
            """,
            {"trade_date": trade_date},
        )
        if prev_df.empty or prev_df.iloc[0].get("prev_trade_date") is None:
            return []
        prev_trade_date = prev_df.iloc[0]["prev_trade_date"]
        prev_hot = self._safe_query(
            self._meta_store,
            """
            SELECT concept_code, concept_name, main_inflow, pct_chg
            FROM concept_money_flow
            WHERE trade_date = :trade_date
            ORDER BY main_inflow DESC NULLS LAST, pct_chg DESC NULLS LAST
            LIMIT 10
            """,
            {"trade_date": prev_trade_date},
        )
        current_hot = self._safe_query(
            self._meta_store,
            """
            SELECT concept_code, concept_name, main_inflow, pct_chg
            FROM concept_money_flow
            WHERE trade_date = :trade_date
            """,
            {"trade_date": trade_date},
        )
        current_map = {
            str(row.concept_code): row._asdict()
            for row in current_hot.itertuples(index=False)
        }
        results: list[dict[str, Any]] = []
        for row in prev_hot.itertuples(index=False):
            current = current_map.get(str(row.concept_code))
            results.append(
                {
                    "concept_code": row.concept_code,
                    "concept_name": row.concept_name,
                    "prev_main_inflow": row.main_inflow,
                    "current_main_inflow": current.get("main_inflow") if current else None,
                    "verdict": "延续" if current else "掉队",
                }
            )
        return results

    def _collect_money_flow_top(
        self,
        store: QueryStore,
        table: str,
        name_field: str,
        code_field: str,
        trade_date: date,
        asc: bool,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        order = "ASC" if asc else "DESC"
        df = self._safe_query(
            store,
            f"""
            SELECT *
            FROM {table}
            WHERE trade_date = :trade_date
            ORDER BY main_inflow {order}, pct_chg {order}
            LIMIT :limit
            """,
            {"trade_date": trade_date, "limit": limit},
        )
        result: list[dict[str, Any]] = []
        for row in df.itertuples(index=False):
            data = row._asdict()
            data["name"] = data.get(name_field)
            data["code"] = data.get(code_field)
            result.append(data)
        return result

    def _safe_query(
        self,
        store: QueryStore,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        try:
            return store.query(sql, params)
        except Exception:
            return pd.DataFrame()

    def _scalar_market(self, sql: str, trade_date: date) -> int:
        df = self._safe_query(self._market_store, sql, {"trade_date": trade_date})
        if df.empty:
            return 0
        if "value" in df.columns:
            value = df.iloc[0]["value"]
        else:
            numeric = df.select_dtypes(include=["number"])
            if not numeric.empty:
                value = numeric.iloc[0].iloc[0]
            else:
                value = 0
        return int(value or 0)


ReviewDataCollector = ReviewCollector


@dataclass(slots=True)
class ReviewSnapshot:
    trade_date: date
    market_duckdb_path: Path
    output_dir: Path
