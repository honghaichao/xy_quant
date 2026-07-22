"""资金流数据 — Agent 数据流适配器。

提供主力资金流、北向资金数据，供 AI 分析师使用。
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd


def _get_pg():
    import psycopg
    from config.settings import settings
    return psycopg.connect(settings.pg_dsn)


def get_stock_money_flow(code: str, days: int = 30) -> pd.DataFrame:
    """获取个股资金流历史。

    Args:
        code: 股票代码
        days: 最近 N 天

    Returns:
        DataFrame: trade_date, main_inflow, main_inflow_pct, super_inflow,
                   big_inflow, mid_inflow, small_inflow
    """
    conn = _get_pg()
    try:
        return pd.read_sql(
            """SELECT trade_date, main_inflow, main_inflow_pct,
                      super_inflow, big_inflow, mid_inflow, small_inflow
               FROM stock_money_flow
               WHERE ts_code LIKE %s
               ORDER BY trade_date DESC
               LIMIT %s""",
            conn, params=[f"%{code}%", days],
        )
    finally:
        conn.close()


def get_latest_intraday_fund_flow(code: str) -> dict | None:
    """获取最新盘中个股资金流（intraday_fund_flow 表）。

    Returns:
        dict 或 None
    """
    import duckdb
    from config.settings import settings

    conn = duckdb.connect(str(settings.duckdb_path), read_only=True)
    try:
        row = conn.execute(
            """SELECT ts_code, name, close, pct_chg,
                      main_inflow, main_inflow_pct,
                      super_inflow, big_inflow, mid_inflow, small_inflow
               FROM intraday_fund_flow
               WHERE ts_code = ?
               ORDER BY fetch_time DESC LIMIT 1""",
            [code],
        ).fetchone()
        if row is None:
            return None
        cols = [c[0] for c in conn.description]
        return dict(zip(cols, row))
    finally:
        conn.close()


def get_sector_money_flow_top(top_n: int = 10) -> pd.DataFrame:
    """获取行业板块资金流排名。

    Returns:
        DataFrame: sector_name, sector_type, pct_chg, main_inflow
    """
    conn = _get_pg()
    try:
        latest = pd.read_sql(
            "SELECT MAX(trade_date) AS dt FROM industry_money_flow",
            conn,
        ).iloc[0]["dt"]
        return pd.read_sql(
            """SELECT industry_name AS sector_name, '行业' AS sector_type,
                      pct_chg, main_inflow
               FROM industry_money_flow
               WHERE trade_date = %s
               ORDER BY main_inflow DESC
               LIMIT %s""",
            conn, params=[latest, top_n],
        )
    finally:
        conn.close()


def format_money_flow_for_llm(code: str) -> str:
    """将资金流数据格式化为 LLM 可读文本。"""
    # 历史个股资金流
    hist_mf = get_stock_money_flow(code, days=20)

    # 盘中个股资金流
    intraday_mf = get_latest_intraday_fund_flow(code)

    # 板块资金流
    sector_mf = get_sector_money_flow_top(10)

    lines = ["## 资金流分析数据\n"]

    # 个股历史资金流
    if not hist_mf.empty:
        recent = hist_mf.head(5)
        total_main = hist_mf["main_inflow"].sum()
        lines.append(f"### {code} — 近 20 日主力累计净流入: {total_main/1e8:.2f} 亿")
        lines.append("近 5 日主力净流入:")
        for _, r in recent.iterrows():
            lines.append(
                f"  {r['trade_date']}: 主力 {r['main_inflow']/1e4:+.1f}万  "
                f"(占比 {r['main_inflow_pct']:+.1f}%)  "
                f"超大单 {r['super_inflow']/1e4:+.1f}万  "
                f"大单 {r['big_inflow']/1e4:+.1f}万"
            )
    else:
        lines.append(f"### {code} — 无资金流数据\n")

    # 盘中个股资金流
    if intraday_mf:
        lines.append(f"### {code} — 盘中资金流实时")
        lines.append(
            f"现价 {intraday_mf.get('close', 'N/A')}  "
            f"涨跌幅 {intraday_mf.get('pct_chg', 0):+.2f}%  "
            f"主力净流入 {intraday_mf.get('main_inflow', 0)/1e4:+.1f}万"
            if isinstance(intraday_mf.get('main_inflow'), (int, float)) else "N/A"
        )
        lines.append(
            f"主力占比 {intraday_mf.get('main_inflow_pct', 0):+.1f}%  "
            f"超大单 {intraday_mf.get('super_inflow', 0)/1e4:+.1f}万"
            if isinstance(intraday_mf.get('super_inflow'), (int, float)) else "N/A"
        )

    # 板块资金流
    if not sector_mf.empty:
        lines.append("### 行业板块资金流 Top 5")
        for _, r in sector_mf.head(5).iterrows():
            flow_str = f"{r['main_inflow']/1e8:.1f}亿" if pd.notna(r["main_inflow"]) else "N/A"
            lines.append(
                f"  {r['sector_name']}: "
                f"涨跌幅 {r['pct_chg']:.2f}%  主力净流入 {flow_str}"
            )

    return "\n".join(lines)
