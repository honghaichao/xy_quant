"""因子分析工具 — 从 SilverM-quant-main 移植并适配 xy_quant 数据层。

提供 IC 分析、分位数收益、因子相关性、换手率、因子报告等功能。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("factor_analysis")

DB_PATH = str(settings.duckdb_path)


class FactorAnalyzer:
    """因子分析器。计算 IC、分位数收益、因子相关性、换手率等。"""

    def __init__(self, factor_df: pd.DataFrame | None = None, returns_df: pd.DataFrame | None = None):
        self.factor_df = factor_df
        self.returns_df = returns_df

    def calculate_ic(
        self, factor_name: str, forward_period: int = 1, method: str = "pearson"
    ) -> pd.DataFrame:
        """计算信息系数 (IC)。"""
        if self.factor_df is None or self.returns_df is None:
            raise ValueError("需要提供因子数据和收益率数据")

        merged = pd.merge(self.factor_df, self.returns_df, on=["date", "code"], how="inner")
        merged = merged.sort_values(["code", "date"])
        merged["future_return"] = merged.groupby("code")["return"].shift(-forward_period)

        ic_list = []
        for dt, group in merged.groupby("date"):
            valid = group[[factor_name, "future_return"]].dropna()
            if len(valid) < 10:
                continue
            if method == "pearson":
                ic, p_value = stats.pearsonr(valid[factor_name], valid["future_return"])
            else:
                ic, p_value = stats.spearmanr(valid[factor_name], valid["future_return"])
            ic_list.append({"date": dt, "ic": ic, "p_value": p_value, "sample_size": len(valid)})

        return pd.DataFrame(ic_list)

    @staticmethod
    def calculate_ic_stats(ic_df: pd.DataFrame) -> dict[str, float]:
        """计算 IC 统计指标。"""
        if ic_df.empty:
            return {}
        ic_series = ic_df["ic"].dropna()
        return {
            "ic_mean": float(ic_series.mean()),
            "ic_std": float(ic_series.std()),
            "ic_ir": float(ic_series.mean() / ic_series.std()) if ic_series.std() != 0 else 0.0,
            "ic_positive_ratio": float((ic_series > 0).sum() / len(ic_series)),
        }

    def calculate_quantile_returns(
        self, factor_name: str, n_quantiles: int = 5, forward_period: int = 1
    ) -> pd.DataFrame:
        """计算分位数收益。"""
        if self.factor_df is None or self.returns_df is None:
            raise ValueError("需要提供因子数据和收益率数据")

        merged = pd.merge(self.factor_df, self.returns_df, on=["date", "code"], how="inner")
        merged = merged.sort_values(["code", "date"])
        merged["future_return"] = merged.groupby("code")["return"].shift(-forward_period)
        merged = merged.dropna(subset=[factor_name, "future_return"])

        quantile_returns = []
        for dt, group in merged.groupby("date"):
            if len(group) < n_quantiles * 10:
                continue
            try:
                group = group.copy()
                group["quantile"] = pd.qcut(
                    group[factor_name], q=n_quantiles,
                    labels=[f"Q{i+1}" for i in range(n_quantiles)], duplicates="drop",
                )
                daily_ret = group.groupby("quantile")["future_return"].mean().to_dict()
                daily_ret["date"] = dt
                daily_ret["long_short"] = daily_ret.get(f"Q{n_quantiles}", 0) - daily_ret.get("Q1", 0)
                quantile_returns.append(daily_ret)
            except ValueError:
                continue

        result = pd.DataFrame(quantile_returns)
        if not result.empty and "date" in result.columns:
            result = result.set_index("date")
        return result

    def calculate_factor_correlation(self, factor_names: list[str]) -> pd.DataFrame:
        """计算因子相关性矩阵。"""
        if self.factor_df is None:
            raise ValueError("需要提供因子数据")
        available = [f for f in factor_names if f in self.factor_df.columns]
        if len(available) < 2:
            raise ValueError("至少需要两个有效因子")
        return self.factor_df[available].corr()

    def calculate_factor_turnover(self, factor_name: str, top_n: int = 50) -> pd.DataFrame:
        """计算因子换手率。"""
        if self.factor_df is None:
            raise ValueError("需要提供因子数据")

        turnover_list = []
        prev_stocks: set[str] = set()
        for dt, group in self.factor_df.sort_values("date").groupby("date"):
            top_stocks = set(group.nlargest(top_n, factor_name)["code"].tolist())
            if prev_stocks:
                common = len(prev_stocks & top_stocks)
                turnover = 1 - common / top_n
            else:
                turnover = 1.0
            turnover_list.append({"date": dt, "turnover": turnover, "stock_count": len(top_stocks)})
            prev_stocks = top_stocks

        return pd.DataFrame(turnover_list)

    def generate_factor_report(
        self, factor_names: list[str], forward_periods: list[int] | None = None
    ) -> dict[str, Any]:
        """生成因子分析报告。"""
        if forward_periods is None:
            forward_periods = [1, 5, 20]

        report: dict[str, Any] = {}

        # IC 分析
        ic_results: dict[str, dict[str, float]] = {}
        for factor in factor_names:
            for period in forward_periods:
                ic_df = self.calculate_ic(factor, period)
                stats_dict = self.calculate_ic_stats(ic_df)
                if stats_dict:
                    ic_results[f"{factor}_{period}d"] = stats_dict
        if ic_results:
            report["ic_analysis"] = pd.DataFrame(ic_results).T

        # 分位数收益
        quantile_results: dict[str, Any] = {}
        for factor in factor_names:
            qdf = self.calculate_quantile_returns(factor, n_quantiles=5)
            if not qdf.empty:
                quantile_results[factor] = qdf.mean().to_dict()
        if quantile_results:
            report["quantile_returns"] = pd.DataFrame(quantile_results).T

        # 因子相关性
        if len(factor_names) >= 2:
            report["factor_correlation"] = self.calculate_factor_correlation(factor_names)

        return report


def load_factor_data(start_date: date, end_date: date, codes: list[str] | None = None) -> pd.DataFrame:
    """Load factor_data from DuckDB."""
    import duckdb

    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        if codes:
            placeholders = ",".join([f"'{c}'" for c in codes])
            df = conn.execute(
                f"""SELECT * FROM factor_data
                    WHERE date >= ? AND date <= ?
                    AND code IN ({placeholders})
                    ORDER BY date, code""",
                [start_date.isoformat(), end_date.isoformat()],
            ).fetchdf()
        else:
            df = conn.execute(
                """SELECT * FROM factor_data
                   WHERE date >= ? AND date <= ?
                   ORDER BY date, code""",
                [start_date.isoformat(), end_date.isoformat()],
            ).fetchdf()
    finally:
        conn.close()
    return df


def load_forward_returns(start_date: date, end_date: date) -> pd.DataFrame:
    """Compute forward returns from daily_bar for IC analysis."""
    import duckdb

    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = conn.execute(
            """SELECT trade_date AS date, ts_code AS code,
                      (LEAD(close, 1) OVER (PARTITION BY ts_code ORDER BY trade_date) - close)
                      / NULLIF(close, 0) AS return
               FROM daily_bar
               WHERE trade_date >= ? AND trade_date <= ?
               ORDER BY ts_code, trade_date""",
            [start_date.isoformat(), end_date.isoformat()],
        ).fetchdf()
    finally:
        conn.close()
    return df.dropna(subset=["return"])


def run_analysis(
    factor_names: list[str],
    start_date: date,
    end_date: date,
    codes: list[str] | None = None,
    forward_periods: list[int] | None = None,
) -> dict[str, Any]:
    """Run factor analysis and save results to DuckDB."""
    import duckdb

    if forward_periods is None:
        forward_periods = [1, 5, 20]

    logger.info(f"Loading factor_data from {start_date} to {end_date}")
    factor_df = load_factor_data(start_date, end_date, codes)

    # Extend date range for forward return calculation
    from datetime import timedelta

    max_period = max(forward_periods)
    returns_df = load_forward_returns(start_date, end_date + timedelta(days=max_period + 5))

    logger.info(f"Factor data: {len(factor_df)} rows, Returns: {len(returns_df)} rows")

    analyzer = FactorAnalyzer(factor_df, returns_df)
    report = analyzer.generate_factor_report(factor_names, forward_periods)

    # Save IC to DuckDB
    conn = duckdb.connect(DB_PATH, read_only=False)
    try:
        for factor in factor_names:
            for period in forward_periods:
                ic_df = analyzer.calculate_ic(factor, period)
                if ic_df.empty:
                    continue
                ic_stats = analyzer.calculate_ic_stats(ic_df)
                for _, row in ic_df.iterrows():
                    conn.execute(
                        """INSERT OR REPLACE INTO factor_ic
                           (date, factor_name, ic, ir, ic_positive_ratio)
                           VALUES (?, ?, ?, ?, ?)""",
                        [
                            row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"]),
                            f"{factor}_{period}d",
                            float(row["ic"]),
                            ic_stats.get("ic_ir", 0.0),
                            ic_stats.get("ic_positive_ratio", 0.0),
                        ],
                    )

        # Save quantile returns
        for factor in factor_names:
            qdf = analyzer.calculate_quantile_returns(factor, n_quantiles=5)
            if qdf.empty:
                continue
            qdf_mean = qdf.mean()
            conn.execute(
                """INSERT OR REPLACE INTO factor_return
                   (date, factor_name, long_short_return, quantile_returns)
                   VALUES (?, ?, ?, ?)""",
                [
                    end_date.isoformat(),
                    factor,
                    float(qdf_mean.get("long_short", 0.0)),
                    qdf_mean.to_json(),
                ],
            )
        logger.info(f"Saved IC data for {len(factor_names)} factors")
    finally:
        conn.close()

    return report
