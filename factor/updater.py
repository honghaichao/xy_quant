"""因子计算 updater — 从 daily_signals.indicators 和 PG 提取因子数据。

策略：从 daily_signals 的 indicators JSON 列提取技术因子（避免重复 OHLCV 计算），
从 PG fina_indicator + daily_basic 提取基本面因子，合并后写入 factor_data。
"""

from __future__ import annotations

import json
from datetime import date
from typing import Sequence

import duckdb
import pandas as pd

from config.settings import settings
from data.updater.base import BaseUpdater
from factor.registry import FactorRegistry
from utils.logger import get_logger

logger = get_logger("factor_updater")

DB_PATH = str(settings.duckdb_path)

# ── Factor definitions ─────────────────────────────────────────────
# Maps factor_data column name → daily_signals.indicators JSON key
# NOTE: indicators in daily_signals are serialized from calculate_indicators()
# which returns these keys per the basic_module.py output.
TECHNICAL_FACTOR_MAP: dict[str, str] = {
    # MACD
    "macd_dif": "dif",
    "macd_dea": "dea",
    "macd_histogram": "macd_histogram",  # computed from dif-dea
    # KDJ
    "kdj_k": "k",
    "kdj_d": "d",
    "kdj_j": "j",
    # RSI
    "rsi_6": "rsi1",   # rsi1 = 14-period
    "rsi_12": "rsi2",  # rsi2 = 14-period variant
    "rsi_24": "rsi3",  # rsi3 = 28-period
    # MA
    "ma_5": "ma5",
    "ma_10": "ma10",
    "ma_20": "ma20",
    "ma_60": "ma60",
    # Volatility
    "volatility_20d": "波动率",  # Chinese name from basic_module
    "_boll_upper": "boll_upper",
    "_boll_mid": "boll_mid",
    "_boll_lower": "boll_lower",
    # Volume
    "volume_ratio": "volume_ratio",
    "turnover_20d": "turnover_20d",
    # Momentum
    "price_momentum_20d": "price_momentum_20d",
    "price_momentum_60d": "price_momentum_60d",
}


def _load_daily_signals_indicators(target_date: date) -> pd.DataFrame | None:
    """Extract technical indicators from daily_signals.indicators JSON column."""
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = conn.execute(
            """SELECT code, "date", indicators
               FROM daily_signals
               WHERE "date" = ?
                 AND indicators IS NOT NULL""",
            [target_date.isoformat()],
        ).fetchdf()
    finally:
        conn.close()

    if df.empty:
        return None

    # Parse indicators JSON → columns
    records = []
    for _, row in df.iterrows():
        try:
            ind = json.loads(row["indicators"]) if isinstance(row["indicators"], str) else row["indicators"]
        except (json.JSONDecodeError, TypeError):
            continue
        rec = {"code": row["code"], "date": target_date}
        for target_col, json_key in TECHNICAL_FACTOR_MAP.items():
            rec[target_col] = float(ind.get(json_key, 0) or 0)

        # Compute missing from existing
        rec["close"] = float(ind.get("close", 0) or 0)
        rec["vol"] = float(ind.get("volume", 0) or 0)
        records.append(rec)

    if not records:
        return None

    result = pd.DataFrame(records)
    # Fill derived columns
    if "macd_dif" in result.columns and "macd_dea" in result.columns:
        result["macd_histogram"] = result["macd_dif"] - result["macd_dea"]
    # Bollinger
    if "boll_mid" not in result.columns or result["boll_mid"].isna().all():
        ma20 = result.get("ma_20", pd.Series(0))
        std20 = result.get("volatility_20d", pd.Series(0))  # approximation
        result["boll_mid"] = ma20
    # Momentum
    if "price_momentum_20d" not in result.columns:
        result["price_momentum_20d"] = 0.0
    if "price_momentum_60d" not in result.columns:
        result["price_momentum_60d"] = 0.0
    # Volatility (use existing or zero)
    if "volatility_20d" not in result.columns:
        result["volatility_20d"] = 0.0
    result["volume_ratio"] = result.get("volume_ratio", 0.0)
    result["turnover_20d"] = result.get("turnover_20d", 0.0)

    logger.info(f"Extracted indicators for {len(result)} stocks from daily_signals")
    return result


def _load_fundamental_factors(target_date: date, codes: list[str]) -> pd.DataFrame:
    """Load fundamental factors from PG fina_indicator and daily_basic."""
    from data.storage.factory import get_meta_store

    fundamentals = []
    store = get_meta_store("postgres")
    try:
        # Use daily_basic for PE/PB/PS (daily frequency, closer to trade date)
        try:
            daily_df = store.query(
                """SELECT ts_code AS code, trade_date AS date,
                          pe, pe_ttm, pb, ps, ps_ttm,
                          total_mv, circ_mv
                   FROM daily_basic
                   WHERE trade_date = %s""",
                [target_date],
            )
            if not daily_df.empty:
                daily_df["code"] = daily_df["code"].str[:6]
                fundamentals.append(daily_df)
        except Exception:
            pass

        # Use fina_indicator for ROE/ROA/gross_margin etc. (quarterly, nearest)
        try:
            fina_df = store.query(
                """SELECT ts_code AS code, end_date,
                          roe, roa, gross_margin, netprofit_margin,
                          debt_to_assets AS debt_to_asset
                   FROM fina_indicator
                   WHERE end_date <= %s
                   ORDER BY end_date DESC
                   LIMIT 10000""",
                [target_date],
            )
            if not fina_df.empty:
                fina_df["code"] = fina_df["code"].str[:6]
                # Take latest per code
                fina_df = fina_df.sort_values("end_date").groupby("code").last().reset_index()
                fina_df["date"] = target_date
                fundamentals.append(fina_df)
        except Exception:
            pass
    finally:
        store.close()

    if not fundamentals:
        return pd.DataFrame()

    result = fundamentals[0]
    for extra in fundamentals[1:]:
        common = [c for c in extra.columns if c not in result.columns or c in ("code", "date")]
        result = result.merge(extra[common], on=["code", "date"], how="outer")

    # Merge down to preferred column names
    for col in ["pe_ttm", "pb", "ps_ttm"]:
        if col not in result.columns:
            result[col] = None

    logger.info(f"Loaded fundamental data for {len(result)} stocks")
    return result


class FactorDataUpdater(BaseUpdater):
    """Compute and persist daily factor_data from signal indicators + fundamentals."""

    source_capability = "daily_bar"

    def run(
        self,
        target_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        ts_codes: Sequence[str] | None = None,
    ) -> dict[str, int]:
        if target_date is None:
            # Default to latest trading day with signals
            conn = duckdb.connect(DB_PATH, read_only=True)
            try:
                row = conn.execute(
                    'SELECT "date" FROM daily_signals ORDER BY "date" DESC LIMIT 1'
                ).fetchone()
                if row is None:
                    logger.warning("No daily_signals data found. Run signal scan first.")
                    return {"factor_data": 0}
                target_date = date.fromisoformat(str(row[0]))
            finally:
                conn.close()

        logger.info(f"Computing factor_data for {target_date}")

        # Step 1: Load technical factors from daily_signals
        tech_df = _load_daily_signals_indicators(target_date)
        if tech_df is None or tech_df.empty:
            logger.warning(f"No daily_signals with indicators for {target_date}")
            return {"factor_data": 0}

        # Step 2: Load fundamental factors from PG
        codes = tech_df["code"].unique().tolist() if ts_codes is None else list(ts_codes)
        fund_df = _load_fundamental_factors(target_date, codes)

        # Step 3: Merge
        factor_df = tech_df.copy()
        if not fund_df.empty:
            fund_cols = [c for c in fund_df.columns if c not in ("code", "date")]
            for c in fund_cols:
                if c in factor_df.columns:
                    factor_df[c] = factor_df[c].fillna(0)
            # Merge on code
            factor_df = factor_df.set_index("code")
            fund_part = fund_df.set_index("code")
            for c in fund_cols:
                if c in fund_part.columns:
                    factor_df[c] = fund_part[c].combine_first(factor_df.get(c))

            # Collect all cols
            all_cols = list(factor_df.columns) + [fc for fc in fund_cols if fc not in factor_df.columns]
            new_df = pd.DataFrame(index=factor_df.index)
            for c in all_cols:
                new_df[c] = factor_df.get(c, fund_part.get(c))
            factor_df = new_df.reset_index().rename(columns={"index": "code"})

        factor_df["date"] = target_date

        # Fill NaN
        factor_df = factor_df.fillna(0)

        # Step 4: Ensure all required columns exist
        all_factor_cols = list(TECHNICAL_FACTOR_MAP.keys()) + [
            "pe_ttm", "pb", "ps_ttm", "pcf_ttm", "dividend_yield",
            "roe", "roa", "gross_margin", "net_margin", "debt_to_asset",
            "revenue_growth_yoy", "profit_growth_yoy",
        ]
        for col in all_factor_cols:
            if col not in factor_df.columns:
                factor_df[col] = 0.0

        # Step 5: Upsert
        if ts_codes:
            factor_df = factor_df[factor_df["code"].isin(ts_codes)]

        keep_cols = ["date", "code"] + [c for c in all_factor_cols if c in factor_df.columns]
        factor_df = factor_df[keep_cols]

        row_count = self._upsert_market("factor_data", factor_df)
        logger.info(f"factor_data: {row_count} rows for {target_date}")

        # Register all factors
        reg = FactorRegistry()
        for col in all_factor_cols:
            if col in factor_df.columns and col not in reg:
                cat = "technical" if col in TECHNICAL_FACTOR_MAP else "fundamental"
                try:
                    reg.register(col, cat, f"{col} factor")
                except Exception:
                    pass

        return {"factor_data": row_count}
