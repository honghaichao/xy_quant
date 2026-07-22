"""盘中分钟数据 + 板块数据 — Agent 数据流适配器。

提供盘中分钟线、市场宽度、板块排名数据，供 AI 分析师使用。
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd


def _get_db():
    import duckdb
    from config.settings import settings
    return duckdb.connect(str(settings.duckdb_path), read_only=True)


def get_minute_bars(code: str, trade_date: date, limit: int = 240) -> pd.DataFrame:
    """获取单只股票当日分钟 K 线。

    Args:
        code: 股票代码 '000001'
        trade_date: 交易日期
        limit: 最多返回条数

    Returns:
        DataFrame: datetime, open, close, high, low, volume, amount
    """
    conn = _get_db()
    try:
        month_str = trade_date.strftime("%Y_%m")
        table = f"minute_bar_{month_str}"
        df = conn.execute(
            f"""SELECT datetime, ts_code AS code, open, close, high, low, volume, amount
                FROM {table}
                WHERE ts_code = ? AND CAST(datetime AS DATE) = ?
                ORDER BY datetime
                LIMIT ?""",
            [code, trade_date.isoformat(), limit],
        ).df()
        return df
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


def get_intraday_spot_snapshot() -> pd.DataFrame:
    """获取最新的全市场盘中快照。

    Returns:
        DataFrame: ts_code, name, close, pct_chg, volume, amount, turnover_rate, pe
    """
    conn = _get_db()
    try:
        latest = conn.execute(
            "SELECT MAX(fetch_time) FROM intraday_spot"
        ).fetchone()[0]
        if latest is None:
            return pd.DataFrame()
        return conn.execute(
            "SELECT * FROM intraday_spot WHERE fetch_time = ?",
            [latest],
        ).df()
    finally:
        conn.close()


def get_market_breadth() -> dict:
    """计算市场宽度（涨跌平分布）。

    Returns:
        {'up': int, 'down': int, 'flat': int, 'total': int, 'up_pct': float}
    """
    df = get_intraday_spot_snapshot()
    if df.empty:
        return {"up": 0, "down": 0, "flat": 0, "total": 0, "up_pct": 0.0}

    total = len(df)
    up = int((df["pct_chg"] > 0).sum())
    down = int((df["pct_chg"] < 0).sum())
    flat = total - up - down
    return {
        "up": up, "down": down, "flat": flat,
        "total": total,
        "up_pct": round(up / total * 100, 1) if total else 0.0,
    }


def get_sector_performance() -> pd.DataFrame:
    """获取行业板块今日表现（盘中 sector_flow + 日线 sector）。

    Returns DataFrame: sector_name, sector_type, pct_chg, main_inflow
    """
    conn = _get_db()
    try:
        latest = conn.execute(
            "SELECT MAX(fetch_time) FROM intraday_sector_flow"
        ).fetchone()[0]
        if latest is None:
            return pd.DataFrame()
        return conn.execute(
            """SELECT sector_name, sector_type, pct_chg, main_inflow
               FROM intraday_sector_flow
               WHERE fetch_time = ?
               ORDER BY main_inflow DESC""",
            [latest],
        ).df()
    finally:
        conn.close()


def format_intraday_for_llm(code: str, trade_date: date) -> str:
    """将盘中分钟线 + 板块数据格式化为 LLM 可读文本。"""
    bars = get_minute_bars(code, trade_date)
    sectors = get_sector_performance()
    breadth = get_market_breadth()

    lines = ["## 盘中数据\n"]

    # 市场宽度
    lines.append("### 全市场宽度")
    lines.append(
        f"上涨 {breadth['up']} 只 ({breadth['up_pct']}%)  |  "
        f"下跌 {breadth['down']} 只  |  平盘 {breadth['flat']} 只\n"
    )

    # 分钟线摘要
    if not bars.empty:
        o = bars.iloc[0]["open"]
        c = bars.iloc[-1]["close"]
        h = bars["high"].max()
        l = bars["low"].min()
        v = bars["volume"].sum()
        chg = (c - o) / o * 100 if o else 0
        lines.append(f"### {code} 分钟线")
        lines.append(
            f"开盘 {o:.2f}  现价 {c:.2f}  最高 {h:.2f}  最低 {l:.2f}  "
            f"涨跌幅 {chg:+.2f}%  总成交量 {v:.0f}\n"
        )
        # 最近 10 根 K 线
        lines.append("最近 10 根 1 分钟 K 线:")
        for _, r in bars.tail(10).iterrows():
            t = str(r["datetime"])[-8:-3]
            lines.append(
                f"  {t}  O={r['open']:.2f}  C={r['close']:.2f}  "
                f"H={r['high']:.2f}  L={r['low']:.2f}  V={r['volume']:.0f}"
            )
    else:
        lines.append(f"### {code} 分钟线: (无盘中数据)\n")

    # 板块排名 Top 5
    if not sectors.empty:
        lines.append("### 行业板块资金流 Top 5")
        for _, r in sectors.head(5).iterrows():
            flow_str = f"{r['main_inflow']/1e4:.1f}亿" if pd.notna(r["main_inflow"]) else "N/A"
            lines.append(
                f"  {r['sector_name']} ({r['sector_type']}): "
                f"涨跌幅 {r['pct_chg']:.2f}%  主力净流入 {flow_str}"
            )

    return "\n".join(lines)
