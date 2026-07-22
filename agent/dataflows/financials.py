"""深度个股数据 — Agent 数据流适配器。

提供完整财务报表、财务比率、行业对比数据。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd


def _get_pg():
    import psycopg
    from config.settings import settings
    return psycopg.connect(settings.pg_dsn)


def _get_db():
    import duckdb
    from config.settings import settings
    return duckdb.connect(str(settings.duckdb_path), read_only=True)


def get_financials(code: str) -> dict:
    """获取最新一期三表核心数据。

    Returns:
        {'income': {...}, 'balance': {...}, 'cashflow': {...}}
    """
    conn = _get_pg()
    try:
        # 最新一期利润表
        income = pd.read_sql(
            """SELECT end_date, total_revenue, revenue, operate_profit,
                      total_profit, n_income, n_income_attr_p, basic_eps
               FROM income
               WHERE ts_code LIKE %s AND report_type = '1'
               ORDER BY end_date DESC LIMIT 4""",
            conn, params=[f"%{code}%"],
        ).to_dict("records") if pd.notna(code) else []

        # 最新一期资产负债表
        balance = pd.read_sql(
            """SELECT end_date, total_assets, total_liab, total_hldr_eqy_inc_min_int,
                      total_cur_assets AS current_assets, total_cur_liab AS current_liab
               FROM balancesheet
               WHERE ts_code LIKE %s AND report_type = '1'
               ORDER BY end_date DESC LIMIT 4""",
            conn, params=[f"%{code}%"],
        ).to_dict("records") if pd.notna(code) else []

        # 最新一期现金流量表
        cashflow = pd.read_sql(
            """SELECT end_date, n_cashflow_act, c_inf_fr_operate_a AS c_fr_sale_sg,
                      n_cashflow_inv_act, n_cash_flows_fnc_act, free_cashflow
               FROM cashflow
               WHERE ts_code LIKE %s AND report_type = '1'
               ORDER BY end_date DESC LIMIT 4""",
            conn, params=[f"%{code}%"],
        ).to_dict("records") if pd.notna(code) else []

        return {"income": income, "balance": balance, "cashflow": cashflow}
    finally:
        conn.close()


def get_fina_indicators(code: str) -> dict:
    """获取财务指标（ROE/ROA/毛利率/净利率/增长率等）。

    Returns:
        指标 dict
    """
    conn = _get_pg()
    try:
        rows = pd.read_sql(
            """SELECT end_date, roe, roa, gross_margin, netprofit_margin,
                      debt_to_assets, current_ratio, quick_ratio
               FROM fina_indicator
               WHERE ts_code LIKE %s
               ORDER BY end_date DESC LIMIT 8""",
            conn, params=[f"%{code}%"],
        )
        if rows.empty:
            return {}
        latest = rows.iloc[0].to_dict()
        # 计算趋势
        trends = {}
        if len(rows) >= 2:
            for col in ["roe", "roa"]:
                if col in rows.columns:
                    cur = rows.iloc[0].get(col)
                    prev = rows.iloc[1].get(col)
                    if cur is not None and prev is not None and pd.notna(cur) and pd.notna(prev):
                        trends[f"{col}_trend"] = "up" if cur > prev else "down"
        return {"latest": latest, "trends": trends, "history": rows.to_dict("records")}
    finally:
        conn.close()


def get_industry_peers(code: str, top_n: int = 10) -> pd.DataFrame:
    """获取同行业可比公司估值对比。

    Returns:
        DataFrame: ts_code, name, pe, pb, roe, total_mv
    """
    conn = _get_pg()
    try:
        # 找该股票的行业
        industry_row = pd.read_sql(
            "SELECT industry FROM stock_basic WHERE ts_code LIKE %s",
            conn, params=[f"%{code}%"],
        )
        if industry_row.empty:
            return pd.DataFrame()
        industry = industry_row.iloc[0]["industry"]

        peers = pd.read_sql(
            """SELECT ts_code, name, industry
               FROM stock_basic WHERE industry = %s AND ts_code != %s
               LIMIT %s""",
            conn, params=[industry, code, top_n + 20],
        )
    finally:
        conn.close()

    if peers.empty:
        return pd.DataFrame()

    # 从 DuckDB 取 PE/PB/总市值
    conn2 = _get_db()
    try:
        peer_codes = peers["ts_code"].str[:6].tolist() + [code]
        placeholders = ",".join(["?"] * len(peer_codes))
        valuations = conn2.execute(
            f"""SELECT ts_code, MAX(trade_date) AS latest_date
                FROM daily_basic
                WHERE ts_code IN ({placeholders})
                GROUP BY ts_code""",
            peer_codes,
        ).fetchall()

        val_map: dict[str, tuple] = {}
        for ts, dt in valuations:
            row = conn2.execute(
                """SELECT ts_code, pe, pb, total_mv
                   FROM daily_basic
                   WHERE ts_code = ? AND trade_date = ?
                   LIMIT 1""",
                [ts, dt],
            ).fetchone()
            if row:
                val_map[ts] = row

        results = []
        for _, p in peers.iterrows():
            peer_code = p["ts_code"]
            if peer_code in val_map:
                _, pe_val, pb_val, mv = val_map[peer_code]
                results.append({
                    "code": peer_code[:6],
                    "name": p["name"],
                    "pe": float(pe_val) if pe_val is not None and pd.notna(pe_val) else None,
                    "pb": float(pb_val) if pb_val is not None and pd.notna(pb_val) else None,
                    "total_mv": float(mv) if mv is not None and pd.notna(mv) else None,
                })

        df = pd.DataFrame(results)
        if not df.empty:
            df = df.dropna(subset=["pe", "pb"]).head(top_n)
            # Normalize values that are clearly in wrong units
            for col in ["total_mv"]:
                if col in df.columns:
                    df[col] = df[col].apply(lambda x: x / 1e4 if x and pd.notna(x) and x > 1e8 else x)
        return df
    finally:
        conn2.close()


def format_financials_for_llm(code: str) -> str:
    """将深度财务数据格式化为 LLM 可读文本。"""
    fin_data = get_financials(code)
    indicators = get_fina_indicators(code)
    peers = get_industry_peers(code)

    lines = ["## 深度财务数据\n"]

    # 财务指标
    if indicators:
        latest = indicators.get("latest", {})
        trends = indicators.get("trends", {})
        lines.append(f"### {code} 核心财务指标")
        lines.append(
            f"ROE: {latest.get('roe', 'N/A')}%  "
            f"ROA: {latest.get('roa', 'N/A')}%  "
            f"毛利率: {latest.get('gross_margin', 'N/A')}%  "
            f"净利率: {latest.get('netprofit_margin', 'N/A')}%"
        )
        lines.append(
            f"资产负债率: {latest.get('debt_to_assets', 'N/A')}%  "
            f"流动比率: {latest.get('current_ratio', 'N/A')}  "
            f"速动比率: {latest.get('quick_ratio', 'N/A')}"
        )
        lines.append(
            f"ROE: {latest.get('roe', 'N/A')}%  "
            f"ROA: {latest.get('roa', 'N/A')}%"
        )
        if trends:
            lines.append(f"趋势: {', '.join(f'{k}={v}' for k, v in trends.items())}")

    # 利润表摘要
    income = fin_data.get("income", [])
    if income:
        lines.append("### 最近报告期利润表")
        for row in income[:2]:
            lines.append(
                f"  {row['end_date']}: 营收 {_safe_val(row, 'total_revenue')} | "
                f"营业利润 {_safe_val(row, 'operate_profit')} | "
                f"净利润 {_safe_val(row, 'n_income_attr_p')}"
            )

    # 行业可比
    if not peers.empty:
        lines.append(f"### 同行业估值对比 (Top {len(peers)})")
        lines.append("  代码      名称        PE     PB     总市值")
        for _, r in peers.iterrows():
            lines.append(
                f"  {r['code']}  {r['name']:<8s}  "
                f"{r['pe']:.1f}  {r['pb']:.2f}  {_fmt_mv(r.get('total_mv'))}"
            )

    return "\n".join(lines)


def _safe_val(row: dict, key: str) -> str:
    v = row.get(key)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    if isinstance(v, (int, float)):
        # Cap absurdly large values (often unit errors: 万元 where 元 expected)
        if abs(v) > 1e9:
            return f"{v/1e8:.2f}亿(疑单位异常)"
        if abs(v) >= 1e8:
            return f"{v/1e8:.2f}亿"
        return f"{v/1e4:.2f}万" if abs(v) >= 1e4 else f"{v:.0f}"
    return str(v)


def _fmt_mv(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "N/A"
    return f"{val/1e8:.1f}亿"
