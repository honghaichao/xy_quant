"""技术指标计算库。从 SilverM-quant-main 移植并适配 xy_quant 数据层。"""

from __future__ import annotations

import numpy as np
import pandas as pd


class TechnicalIndicators:
    """Vectorized technical indicator calculator.

    Accepts a DataFrame with OHLCV columns and returns indicator DataFrames.
    Compatible with xy_quant daily_bar format (trade_date, ts_code, open, high, low, close, vol).
    """

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df.sort_values("trade_date").reset_index(drop=True)
        self.close = self.df["close"]
        self.open = self.df["open"]
        self.high = self.df["high"]
        self.low = self.df["low"]
        self.volume = self.df["vol"]

    # ── MA ─────────────────────────────────────────────────────

    def ma(self, period: int = 20) -> pd.Series:
        return self.close.rolling(window=period).mean()

    def ema(self, period: int = 20) -> pd.Series:
        return self.close.ewm(span=period, adjust=False).mean()

    # ── MACD ───────────────────────────────────────────────────

    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        ema_fast = self.ema(fast)
        ema_slow = self.ema(slow)
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        histogram = dif - dea
        return pd.DataFrame({"macd_dif": dif, "macd_dea": dea, "macd_histogram": histogram})

    # ── KDJ ────────────────────────────────────────────────────

    def kdj(self, n: int = 9) -> pd.DataFrame:
        low_n = self.low.rolling(window=n, min_periods=n).min()
        high_n = self.high.rolling(window=n, min_periods=n).max()
        rsv = (self.close - low_n) / (high_n - low_n) * 100.0
        k = pd.Series(50.0, index=self.close.index)
        d = pd.Series(50.0, index=self.close.index)
        for i in range(n - 1, min(len(k), len(rsv))):
            if pd.isna(rsv.iloc[i]):
                k.iloc[i] = k.iloc[i - 1]
                d.iloc[i] = d.iloc[i - 1]
            else:
                k.iloc[i] = (2 / 3) * k.iloc[i - 1] + (1 / 3) * rsv.iloc[i]
                d.iloc[i] = (2 / 3) * d.iloc[i - 1] + (1 / 3) * k.iloc[i]
        j = 3 * k - 2 * d
        return pd.DataFrame({"kdj_k": k, "kdj_d": d, "kdj_j": j})

    # ── RSI ────────────────────────────────────────────────────

    def rsi(self, period: int = 14) -> pd.Series:
        delta = self.close.diff()
        gain = delta.clip(lower=0).rolling(window=period).mean()
        loss = (-delta.clip(upper=0)).rolling(window=period).mean()
        rs = gain / loss.replace(0, 1e-9)
        return 100.0 - (100.0 / (1.0 + rs))

    # ── Bollinger ──────────────────────────────────────────────

    def bollinger_bands(self, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
        mid = self.ma(period)
        std = self.close.rolling(window=period).std()
        return pd.DataFrame(
            {"boll_upper": mid + std * std_dev, "boll_mid": mid, "boll_lower": mid - std * std_dev}
        )

    # ── Volatility ─────────────────────────────────────────────

    def volatility(self, period: int = 20) -> pd.Series:
        returns = self.close.pct_change()
        return returns.rolling(window=period).std() * np.sqrt(252)

    def atr(self, period: int = 14) -> pd.Series:
        high_low = self.high - self.low
        high_close = (self.high - self.close.shift()).abs()
        low_close = (self.low - self.close.shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    # ── Volume ─────────────────────────────────────────────────

    def volume_ma(self, period: int = 20) -> pd.Series:
        return self.volume.rolling(window=period).mean()

    def obv(self) -> pd.Series:
        direction = np.sign(self.close.diff()).fillna(0)
        return (direction * self.volume).cumsum()

    # ── Momentum ───────────────────────────────────────────────

    def momentum(self, period: int = 20) -> pd.Series:
        return self.close / self.close.shift(period) - 1.0

    def turnover_20d(self) -> pd.Series:
        """20-day average turnover rate (approximation: vol / vol_ma20)."""
        ma20 = self.volume_ma(20)
        return self.volume / ma20.replace(0, 1e-9)

    def volume_ratio(self) -> pd.Series:
        """Volume ratio = today's volume / 5-day average volume."""
        ma5 = self.volume_ma(5)
        return self.volume / ma5.replace(0, 1e-9)

    # ── MA偏离度 ────────────────────────────────────────────────

    def ma_deviation(self, period: int = 60) -> pd.Series:
        """Price deviation from MA = (close - MA) / MA."""
        ma_val = self.ma(period)
        return (self.close - ma_val) / ma_val.replace(0, 1e-9)

    # ── All ────────────────────────────────────────────────────

    def calculate_all(self) -> pd.DataFrame:
        """Compute all technical indicators and return as a wide DataFrame."""
        result = pd.DataFrame(index=self.df.index)
        result["trade_date"] = self.df["trade_date"]
        result["ts_code"] = self.df["ts_code"]
        result["close"] = self.close
        result["vol"] = self.volume

        # MA
        for p in (5, 10, 20, 60):
            result[f"ma_{p}"] = self.ma(p)

        # MACD
        macd_df = self.macd()
        result["macd_dif"] = macd_df["macd_dif"]
        result["macd_dea"] = macd_df["macd_dea"]
        result["macd_histogram"] = macd_df["macd_histogram"]

        # KDJ
        kdj_df = self.kdj()
        result["kdj_k"] = kdj_df["kdj_k"]
        result["kdj_d"] = kdj_df["kdj_d"]
        result["kdj_j"] = kdj_df["kdj_j"]

        # RSI
        result["rsi_6"] = self.rsi(6)
        result["rsi_12"] = self.rsi(12)
        result["rsi_24"] = self.rsi(24)

        # Bollinger
        bb_df = self.bollinger_bands()
        result["boll_upper"] = bb_df["boll_upper"]
        result["boll_mid"] = bb_df["boll_mid"]
        result["boll_lower"] = bb_df["boll_lower"]

        # Volatility
        result["volatility_20d"] = self.volatility(20)
        result["atr_14"] = self.atr(14)

        # Volume
        result["volume_ratio"] = self.volume_ratio()
        result["turnover_20d"] = self.turnover_20d()

        # Momentum
        result["price_momentum_20d"] = self.momentum(20)
        result["price_momentum_60d"] = self.momentum(60)

        return result
