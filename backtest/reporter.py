"""
回测报告输出 — 统一所有策略的报告生成。

职责：
  - save_to_db(): 持久化到 DuckDB（英文列名）
  - write_trades_csv(): 交易记录 CSV（中文列头：日期,代码,名称,方向,价格,数量,金额,佣金,盈亏,盈亏%）
  - write_daily_positions_csv(): 每日持仓 CSV
  - write_summary_txt(): 完整中文汇总报告
  - plot_equity_curve(): 权益曲线 + 回撤子图 PNG
  - plot_metrics_dashboard(): KPI 瓦片 + 月度热力图 PNG
  - plot_trade_pnl_distribution(): 盈亏分布 PNG
"""

from __future__ import annotations

import csv
import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from utils.logger import get_logger

logger = get_logger("backtest.reporter")

plt.rcParams["font.sans-serif"] = ["Heiti TC", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = str(PROJECT_ROOT / "data_store" / "market.duckdb")


# ═══════════════════════════════════════════════════════════════
# DuckDB 持久化（英文列名）
# ═══════════════════════════════════════════════════════════════

def save_to_db(
    result: dict,
    run_id: str,
    strategy_name: str,
    start_dt: date,
    end_dt: date,
    strategy_params: dict | None = None,
    universe_desc: str = "全市场(排除科创北交)",
    benchmark_code: str = "000300.SH",
) -> str:
    """将回测结果写入 DuckDB backtest_run/perf/trades/daily_pnl 四表。

    Args:
        result: {initial_cash, metrics: {...}, trades: [...], equity_curve: [...], daily_positions: [...]}
        run_id: 如果传 None 则自动生成
        strategy_name: 策略中文名称
        start_dt, end_dt: 回测区间
        strategy_params: 策略参数 dict
        universe_desc: 选股池描述
        benchmark_code: 基准代码

    Returns:
        run_id
    """
    if run_id is None:
        run_id = f"bt_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"

    initial_cash = result.get("initial_cash", 500_000)
    metrics = result.get("metrics", {})

    conn = duckdb.connect(DB_PATH, read_only=False)
    try:
        # 1. backtest_run
        conn.execute(
            """INSERT INTO backtest_run (run_id, strategy_name, strategy_params,
               start_date, end_date, universe, benchmark, initial_capital, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed')""",
            [
                run_id,
                strategy_name,
                json.dumps(strategy_params or {}),
                start_dt,
                end_dt,
                universe_desc,
                benchmark_code,
                initial_cash,
            ],
        )

        # 2. backtest_performance
        conn.execute(
            """INSERT INTO backtest_performance
               (run_id, total_return, annual_return, max_drawdown, sharpe_ratio,
                sortino_ratio, calmar_ratio, annual_volatility,
                win_rate, total_trades, avg_holding_days)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                run_id,
                round(metrics.get("total_return", 0), 6),
                round(metrics.get("annual_return", 0), 6),
                round(metrics.get("max_drawdown", 0), 6),
                round(metrics.get("sharpe_ratio", 0), 6),
                round(metrics.get("sortino_ratio", 0), 6),
                round(metrics.get("calmar_ratio", 0), 6),
                round(metrics.get("annual_volatility", 0), 6),
                round(metrics.get("win_rate", 0), 6),
                metrics.get("total_trades", 0),
                None,  # avg_holding_days
            ],
        )

        # 3. backtest_trades
        conn.execute("DELETE FROM backtest_trades WHERE run_id = ?", [run_id])
        trades = result.get("trades", [])
        for i, t in enumerate(trades):
            conn.execute(
                """INSERT INTO backtest_trades
                   (id, run_id, datetime, code, action, price, size, amount, commission)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    i, run_id, t["date"],
                    t.get("code", ""),
                    "BUY" if t.get("action") in ("买入", "buy") else "SELL",
                    t.get("price", 0), t.get("shares", 0),
                    t.get("amount", 0), t.get("commission", 0),
                ],
            )

        # 4. backtest_daily_pnl
        conn.execute("DELETE FROM backtest_daily_pnl WHERE run_id = ?", [run_id])
        prev_value = initial_cash
        for d in result.get("equity_curve", []):
            cur = d["total"]
            pnl = cur - prev_value
            pnl_pct = (pnl / prev_value) if prev_value else 0.0
            prev_value = cur
            conn.execute(
                """INSERT INTO backtest_daily_pnl (run_id, date, pnl, pnl_pct, total_value, positions)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    run_id, d["date"],
                    round(pnl, 2), round(pnl_pct, 6), round(cur, 2),
                    json.dumps({"count": d.get("positions", 0)}),
                ],
            )

        logger.info(f"回测结果已保存到数据库, run_id={run_id}")
    finally:
        conn.close()

    return run_id


# ═══════════════════════════════════════════════════════════════
# CSV 输出（中文列头）
# ═══════════════════════════════════════════════════════════════

def write_trades_csv(trades: list[dict], save_path: str):
    """写交易记录 CSV — 中文列头，含代码+名称"""
    if not trades:
        return
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "日期", "代码", "名称", "方向", "价格", "数量", "金额", "佣金", "盈亏", "盈亏%"
        ])
        w.writeheader()
        for t in trades:
            w.writerow({
                "日期": str(t.get("date", "")),
                "代码": t.get("code", ""),
                "名称": t.get("name", t.get("code", "")),
                "方向": t.get("action", ""),
                "价格": t.get("price", 0),
                "数量": t.get("shares", 0),
                "金额": t.get("amount", 0),
                "佣金": t.get("commission", 0),
                "盈亏": t.get("pnl", 0),
                "盈亏%": t.get("pnl_pct", 0),
            })
    logger.info(f"交易记录: {save_path} ({len(trades)} 条)")


def write_daily_positions_csv(positions: list[dict], save_path: str):
    """写每日持仓 CSV — 中文列头"""
    if not positions:
        return
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["日期", "持仓代码", "持仓数"])
        w.writeheader()
        for p in positions:
            w.writerow({
                "日期": str(p.get("date", "")),
                "持仓代码": p.get("codes", ""),
                "持仓数": p.get("count", 0),
            })
    logger.info(f"每日持仓: {save_path}")


# ═══════════════════════════════════════════════════════════════
# 汇总报告 TXT
# ═══════════════════════════════════════════════════════════════

def write_summary_txt(result: dict, strategy_name: str, save_path: str) -> str:
    """写完整中文回测报告 TXT"""
    m = result.get("metrics", {})
    lines = []
    lines.append("=" * 65)
    lines.append(f"  {strategy_name} — 回测报告")
    lines.append("=" * 65)
    lines.append(f"  回测区间:     {result.get('start', '')} ~ {result.get('end', '')}")
    lines.append(f"  交易日数:     {m.get('trading_days', 0)}")
    lines.append(f"  初始资金:     ¥{result.get('initial_cash', 0):,.0f}")
    lines.append(f"  最终资金:     ¥{result.get('final_value', 0):,.0f}")
    ret = m.get("total_return", 0) * 100
    profit = result.get("final_value", 0) - result.get("initial_cash", 0)
    lines.append(f"  总收益率:     {ret:+.2f}%  (¥{profit:+,.0f})")
    lines.append(f"  年化收益率:   {m.get('annual_return', 0)*100:+.2f}%")
    lines.append(f"  年化波动率:   {m.get('annual_volatility', 0)*100:.2f}%")
    lines.append("")
    lines.append("-" * 65)
    lines.append("  风险指标")
    lines.append("-" * 65)
    lines.append(f"  夏普比率:     {m.get('sharpe_ratio', 0):.4f}")
    lines.append(f"  索提诺比率:   {m.get('sortino_ratio', 0):.4f}")
    lines.append(f"  卡玛比率:     {m.get('calmar_ratio', 0):.4f}")
    lines.append(f"  最大回撤:     {m.get('max_drawdown', 0)*100:.2f}%")
    lines.append(f"  盈亏比:       {m.get('profit_loss_ratio', 0):.2f}")
    lines.append("")
    lines.append("-" * 65)
    lines.append("  交易统计")
    lines.append("-" * 65)
    lines.append(f"  总交易次数:   {m.get('total_trades', 0)}")
    lines.append(f"  买入次数:     {m.get('num_buys', 0)}")
    lines.append(f"  卖出次数:     {m.get('num_sells', 0)}")
    lines.append(f"  胜率:         {m.get('win_rate', 0)*100:.1f}%")
    lines.append(f"  盈利交易:     {m.get('winning_trades', 0)}")
    lines.append(f"  亏损交易:     {m.get('losing_trades', 0)}")
    lines.append("")
    lines.append("-" * 65)
    lines.append("  交易明细（最后 20 条）")
    lines.append("-" * 65)
    lines.append(f"  {'日期':<12s} {'代码':<8s} {'方向':<4s} {'价格':>8s} {'数量':>6s} {'盈亏':>12s}")
    for t in result.get("trades", [])[-20:]:
        lines.append(
            f"  {str(t.get('date', '')):<12s} {t.get('code', ''):<8s} {t.get('action', ''):<4s} "
            f"{t.get('price', 0):>8.2f} {t.get('shares', 0):>6d} {t.get('pnl', 0):>+12.2f}"
        )
    lines.append("=" * 65)

    text = "\n".join(lines)
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info(f"汇总报告: {save_path}")
    return text


# ═══════════════════════════════════════════════════════════════
# 图表绘制
# ═══════════════════════════════════════════════════════════════

def plot_equity_curve(
    result: dict,
    save_path: str,
    benchmark_df: pd.DataFrame | None = None,
):
    """权益曲线 + 回撤子图"""
    df = pd.DataFrame(result["equity_curve"])
    df["date"] = pd.to_datetime(df["date"])
    ret_pct = df["total_return"] * 100
    dd_series = (df["total"] / df["total"].cummax() - 1) * 100
    strategy_name = result.get("strategy_name", "策略")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10),
                                     gridspec_kw={"height_ratios": [2.5, 1]}, sharex=True)
    fig.patch.set_facecolor("#FAFAFA")

    # 权益曲线
    ax1.plot(df["date"], ret_pct, color="#2C7FB8", linewidth=2.2, label=strategy_name, zorder=3)
    ax1.fill_between(df["date"], 0, ret_pct, where=ret_pct >= 0, color="#2C7FB8", alpha=0.12)
    ax1.fill_between(df["date"], 0, ret_pct, where=ret_pct < 0, color="#D73027", alpha=0.12)
    if benchmark_df is not None and not benchmark_df.empty:
        bench_initial = float(benchmark_df.iloc[0]["close"])
        bench_ret = [(float(benchmark_df.iloc[i]["close"]) / bench_initial - 1) * 100 for i in range(len(benchmark_df))]
        ax1.plot(benchmark_df["trade_date"], bench_ret, color="#FC8D62", linewidth=1.5,
                 linestyle="--", label="沪深300", alpha=0.85, zorder=2)
    ax1.axhline(y=0, color="#999999", linestyle="-", linewidth=0.8)
    ax1.set_ylabel("累计收益率 (%)", fontsize=12)
    ax1.legend(loc="upper left", framealpha=0.9, fontsize=10)
    ax1.grid(True, alpha=0.25, linestyle="--")
    final_ret = ret_pct.iloc[-1]
    ax1.annotate(f"最终: {final_ret:+.2f}%", xy=(df["date"].iloc[-1], final_ret),
                 xytext=(20, 0), textcoords="offset points", fontsize=10,
                 color="#2C7FB8", fontweight="bold", va="center",
                 arrowprops=dict(arrowstyle="->", color="#2C7FB8", lw=1))
    ax1.set_title(f"{strategy_name} — 权益曲线 ({result.get('start', '')} ~ {result.get('end', '')})",
                  fontsize=15, fontweight="bold", pad=12)

    # 回撤
    ax2.fill_between(df["date"], dd_series, 0, color="#D73027", alpha=0.35)
    ax2.plot(df["date"], dd_series, color="#D73027", linewidth=1.2)
    max_idx = dd_series.idxmin()
    ax2.annotate(f"最大回撤: {dd_series.iloc[max_idx]:.1f}%",
                 xy=(df["date"].iloc[max_idx], dd_series.iloc[max_idx]),
                 xytext=(0, -20), textcoords="offset points", fontsize=9,
                 color="#D73027", fontweight="bold", ha="center",
                 arrowprops=dict(arrowstyle="->", color="#D73027", lw=1.2))
    ax2.set_ylabel("回撤 (%)", fontsize=12)
    ax2.set_xlabel("日期", fontsize=12)
    ax2.grid(True, alpha=0.25, linestyle="--")
    ax2.invert_yaxis()
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=9)

    plt.tight_layout()
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    plt.savefig(save_path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    logger.info(f"权益曲线图: {save_path}")


def plot_metrics_dashboard(result: dict, save_path: str):
    """绩效仪表盘 — KPI 瓦片 + 日收益分布 + 月度热力图"""
    df = pd.DataFrame(result["equity_curve"])
    df["date"] = pd.to_datetime(df["date"])
    df["daily_return"] = df["total"].pct_change().fillna(0)
    m = result.get("metrics", {})
    strategy_name = result.get("strategy_name", "策略")

    fig = plt.figure(figsize=(18, 10), facecolor="#FAFAFA")
    gs = fig.add_gridspec(3, 4, hspace=0.5, wspace=0.4)

    def _tile(ax, value, label, fmt, color="#2C7FB8", subtitle=""):
        ax.set_facecolor("#F8F8F8")
        ax.text(0.5, 0.55, fmt.format(value), transform=ax.transAxes,
                fontsize=28, fontweight="bold", color=color, ha="center", va="center")
        ax.text(0.5, 0.15, label, transform=ax.transAxes,
                fontsize=11, color="#555555", ha="center", va="center")
        if subtitle:
            ax.text(0.5, 0.02, subtitle, transform=ax.transAxes,
                    fontsize=8, color="#888888", ha="center", va="center")
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color("#DDDDDD")

    ret_pct = m.get("total_return", 0) * 100

    ax1 = fig.add_subplot(gs[0, 0])
    _tile(ax1, ret_pct, "总收益率", "{:+.2f}%", color="#2C7FB8" if ret_pct >= 0 else "#D73027")
    ax2 = fig.add_subplot(gs[0, 1])
    _tile(ax2, m.get("sharpe_ratio", 0), "夏普比率", "{:.2f}", subtitle=f"Sortino: {m.get('sortino_ratio', 0):.2f}")
    ax3 = fig.add_subplot(gs[0, 2])
    _tile(ax3, m.get("max_drawdown", 0) * 100, "最大回撤", "{:.2f}%", color="#D73027",
          subtitle=f"Calmar: {m.get('calmar_ratio', 0):.2f}")
    ax4 = fig.add_subplot(gs[0, 3])
    _tile(ax4, m.get("win_rate", 0) * 100, "胜率", "{:.1f}%",
          subtitle=f"年化波动: {m.get('annual_volatility', 0)*100:.1f}%")

    # 日收益分布
    ax_hist = fig.add_subplot(gs[1, :2])
    daily_rets = df["daily_return"].dropna() * 100
    ax_hist.hist(daily_rets, bins=40, edgecolor="white", alpha=0.85, color="#2C7FB8")
    ax_hist.axvline(x=0, color="#999999", linestyle="-", linewidth=0.8)
    ax_hist.axvline(x=daily_rets.mean(), color="#D73027", linestyle="--", linewidth=1.5,
                    label=f"均值: {daily_rets.mean():+.2f}%")
    ax_hist.set_xlabel("日收益率 (%)", fontsize=10)
    ax_hist.set_ylabel("天数", fontsize=10)
    ax_hist.set_title("日收益率分布", fontsize=12, fontweight="bold")
    ax_hist.legend(fontsize=9)

    # 权益 mini
    ax_mini = fig.add_subplot(gs[1, 2:])
    init_cash = result.get("initial_cash", 500000)
    ax_mini.plot(df["date"], df["total"], color="#2C7FB8", linewidth=1.5)
    ax_mini.fill_between(df["date"], init_cash, df["total"], where=df["total"] >= init_cash,
                         color="#2C7FB8", alpha=0.1)
    ax_mini.fill_between(df["date"], init_cash, df["total"], where=df["total"] < init_cash,
                         color="#D73027", alpha=0.1)
    ax_mini.axhline(y=init_cash, color="#999999", linestyle="--", linewidth=0.8)
    ax_mini.set_ylabel("账户总值 (¥)", fontsize=9)
    ax_mini.set_title("权益走势", fontsize=12, fontweight="bold")
    ax_mini.tick_params(labelsize=8)
    ax_mini.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

    # 月度热力图
    ax_month = fig.add_subplot(gs[2, :])
    df["year"] = df["date"].dt.year
    df["month_num"] = df["date"].dt.month
    monthly = df.groupby(["year", "month_num"]).apply(
        lambda g: g["total"].iloc[-1] / g["total"].iloc[0] - 1, include_groups=False
    ).unstack(level=0) * 100
    if not monthly.empty:
        im = ax_month.imshow(monthly.values, cmap="RdYlGn", aspect="auto", vmin=-10, vmax=10)
        ax_month.set_xticks(range(len(monthly.columns)))
        ax_month.set_xticklabels([str(int(y)) for y in monthly.columns], fontsize=10)
        ax_month.set_yticks(range(len(monthly.index)))
        ax_month.set_yticklabels([f"{int(m)}月" for m in monthly.index], fontsize=10)
        for i in range(len(monthly.index)):
            for j in range(len(monthly.columns)):
                val = monthly.iloc[i, j]
                if not np.isnan(val):
                    ax_month.text(j, i, f"{val:+.1f}%", ha="center", va="center",
                                  fontsize=10, fontweight="bold",
                                  color="white" if abs(val) > 5 else "#333333")
        ax_month.set_title("月度收益热力图 (%)", fontsize=12, fontweight="bold")
        plt.colorbar(im, ax=ax_month, shrink=0.8)

    fig.suptitle(f"{strategy_name} — 绩效总览 (¥{result.get('initial_cash', 0):,.0f} → ¥{result.get('final_value', 0):,.0f})",
                 fontsize=16, fontweight="bold", y=1.01)
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    plt.savefig(save_path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    logger.info(f"绩效仪表盘: {save_path}")


def plot_trade_pnl_distribution(trades: list[dict], save_path: str):
    """交易盈亏分布图"""
    sells = [t for t in trades if t.get("action") in ("卖出", "sell")]
    if not sells:
        return
    pnls = [t.get("pnl", 0) for t in sells]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), facecolor="#FAFAFA")

    axes[0].hist(pnls, bins=30, edgecolor="white", alpha=0.85, color="#2C7FB8")
    axes[0].axvline(x=0, color="#333333", linestyle="-", linewidth=0.8)
    axes[0].axvline(x=np.mean(pnls), color="#D73027", linestyle="--", linewidth=1.5,
                    label=f"均值: ¥{np.mean(pnls):+.0f}")
    axes[0].set_xlabel("盈亏 (¥)", fontsize=10)
    axes[0].set_ylabel("次数", fontsize=10)
    axes[0].set_title("交易盈亏分布", fontsize=12, fontweight="bold")
    axes[0].legend(fontsize=9)

    # 累计盈亏走势
    cum_pnl = []
    running = 0
    for t in trades:
        if t.get("action") in ("卖出", "sell"):
            running += t.get("pnl", 0)
        cum_pnl.append({"date": t["date"], "cum_pnl": running})
    if cum_pnl:
        cum_df = pd.DataFrame(cum_pnl)
        cum_df["date"] = pd.to_datetime(cum_df["date"])
        axes[1].plot(cum_df["date"], cum_df["cum_pnl"], color="#2C7FB8", linewidth=1.5)
        axes[1].fill_between(cum_df["date"], 0, cum_df["cum_pnl"],
                             where=cum_df["cum_pnl"] >= 0, color="#2C7FB8", alpha=0.12)
        axes[1].fill_between(cum_df["date"], 0, cum_df["cum_pnl"],
                             where=cum_df["cum_pnl"] < 0, color="#D73027", alpha=0.12)
        axes[1].axhline(y=0, color="#999999", linestyle="-", linewidth=0.8)
        axes[1].set_ylabel("累计交易盈亏 (¥)", fontsize=10)
        axes[1].set_title("累计交易盈亏走势", fontsize=12, fontweight="bold")
        axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        plt.setp(axes[1].xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=8)

    plt.tight_layout()
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    plt.savefig(save_path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    logger.info(f"盈亏分布图: {save_path}")


def generate_all_reports(
    result: dict,
    strategy_name: str,
    report_dir: str,
    benchmark_df: pd.DataFrame | None = None,
    save_db: bool = True,
    run_id: str | None = None,
    strategy_params: dict | None = None,
    start_dt: date | None = None,
    end_dt: date | None = None,
) -> str:
    """一键生成全部报告。

    Returns:
        run_id (数据库ID 或 '' 表示未保存)
    """
    os.makedirs(report_dir, exist_ok=True)

    # 报表
    write_trades_csv(result.get("trades", []), os.path.join(report_dir, "trades.csv"))
    write_daily_positions_csv(result.get("daily_positions", []), os.path.join(report_dir, "daily_positions.csv"))
    write_summary_txt(result, strategy_name, os.path.join(report_dir, "report_summary.txt"))

    # 图表
    plot_equity_curve(result, os.path.join(report_dir, "equity_curve.png"), benchmark_df=benchmark_df)
    plot_metrics_dashboard(result, os.path.join(report_dir, "metrics_dashboard.png"))
    plot_trade_pnl_distribution(result.get("trades", []), os.path.join(report_dir, "trade_pnl_dist.png"))

    # 数据库
    db_id = ""
    if save_db:
        db_id = save_to_db(
            result, run_id, strategy_name,
            start_dt=start_dt or date.today(),
            end_dt=end_dt or date.today(),
            strategy_params=strategy_params,
        )

    logger.info(f"全部报告已保存到: {report_dir}")
    if db_id:
        logger.info(f"Web 查看: http://localhost:5004/backtest/{db_id}")

    return db_id
