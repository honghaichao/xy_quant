"""
回测引擎 - 基于backtrader的封装，适配 xy_quant 数据层。
"""
import backtrader as bt
import pandas as pd
import numpy as np
import duckdb
from typing import Dict, List, Optional, Any, Type
from datetime import datetime, date
from pathlib import Path
from dataclasses import dataclass

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("backtest")

DB_PATH = str(Path(settings.duckdb_path))


@dataclass
class PerformanceMetrics:
    """回测性能指标数据类"""
    total_return: float
    annual_return: float
    benchmark_return: float
    excess_return: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    max_drawdown_duration: int
    volatility: float
    win_rate: float
    profit_loss_ratio: float
    total_trades: int


class BacktestEngine:
    """回测引擎，封装backtrader，提供简洁的回测接口。"""

    def __init__(
        self,
        initial_cash: float = 100000.0,
        commission: float = 0.0003,
        stamp_duty: float = 0.001,
        slip_page: float = 0.001,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        stock_list: Optional[List[str]] = None,
        stock_file: Optional[str] = None,
    ):
        self.initial_cash = initial_cash
        self.commission = commission
        self.stamp_duty = stamp_duty
        self.slip_page = slip_page
        self.start_date = start_date
        self.end_date = end_date

        self._stock_list = None
        if stock_file:
            self._stock_list = self._load_stock_list_from_file(stock_file)
        elif stock_list:
            self._stock_list = [str(c).strip() for c in stock_list]

        self.cerebro = bt.Cerebro()
        self.cerebro.broker.setcash(initial_cash)
        self.cerebro.broker.setcommission(commission=commission)
        self.cerebro.broker.set_slippage_perc(slip_page)
        self._add_analyzers()

        self._conn: Optional[duckdb.DuckDBPyConnection] = None
        self.results = None
        self.run_id: Optional[str] = None

    # ---------- helpers ----------
    def _get_conn(self, read_only: bool = True) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(DB_PATH, read_only=read_only)

    @staticmethod
    def _load_stock_list_from_file(file_path: str) -> List[str]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"股票列表文件不存在: {file_path}")
        with open(path, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]

    @staticmethod
    def _code_to_ts_code(code: str) -> str:
        code = str(code)
        return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"

    def get_stock_list(self) -> Optional[List[str]]:
        return self._stock_list

    # ---------- analyzers ----------
    def _add_analyzers(self) -> None:
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        self.cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="timereturn")
        self.cerebro.addanalyzer(bt.analyzers.PositionsValue, _name="positions")

    # ---------- data ----------
    def add_data(
        self,
        df: pd.DataFrame,
        name: Optional[str] = None,
        fromdate: Optional[date] = None,
        todate: Optional[date] = None,
    ) -> None:
        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"数据缺少必需列: {col}")

        if "datetime" not in df.columns:
            if "date" in df.columns:
                df["datetime"] = pd.to_datetime(df["date"])
            else:
                raise ValueError("数据需要包含'date'或'datetime'列")

        df = df.set_index("datetime").dropna()
        ef = fromdate or self.start_date
        et = todate or self.end_date
        if ef:
            if isinstance(ef, str):
                ef = pd.Timestamp(ef)
            df = df[df.index >= ef]
        if et:
            if isinstance(et, str):
                et = pd.Timestamp(et)
            df = df[df.index <= et]

        bt_fromdate = ef.to_pydatetime().date() if ef else None
        bt_todate = et.to_pydatetime().date() if et else None
        data = bt.feeds.PandasData(dataname=df, name=name, fromdate=bt_fromdate, todate=bt_todate)
        self.cerebro.adddata(data, name=name)

    def add_data_from_db(
        self,
        code: str,
        fromdate: Optional[date] = None,
        todate: Optional[date] = None,
    ) -> None:
        if self._stock_list is not None and code not in self._stock_list:
            return
        ef = fromdate or self.start_date
        et = todate or self.end_date
        ts_code = self._code_to_ts_code(code)

        conn = self._get_conn(read_only=True)
        try:
            df = conn.execute(
                """SELECT ts_code, trade_date, open, high, low, close, vol
                   FROM daily_bar
                   WHERE ts_code = ?
                   ORDER BY trade_date""",
                [ts_code],
            ).fetchdf()
        finally:
            conn.close()

        if df.empty:
            raise ValueError(f"数据库中没有 {code} ({ts_code}) 的数据")

        df = df.rename(columns={"trade_date": "date", "vol": "volume"})
        if ef:
            df = df[df["date"] >= str(ef)]
        if et:
            df = df[df["date"] <= str(et)]
        if df.empty:
            raise ValueError(f"日期范围内没有 {code} 的数据")
        self.add_data(df, name=code, fromdate=fromdate, todate=todate)

    def add_strategy(self, strategy_class: Type[bt.Strategy], **kwargs: Any) -> None:
        self.cerebro.addstrategy(strategy_class, **kwargs)

    # ---------- run ----------
    def run(self, strategy_name: Optional[str] = None, save_results: bool = True) -> Dict[str, Any]:
        logger.info(f"开始回测，初始资金: {self.initial_cash:,.2f}")
        self.results = self.cerebro.run()
        strat = self.results[0]
        result = self._extract_results(strat)
        if save_results:
            self._save_to_db(strategy_name or "UnknownStrategy", result)
        self._print_results(result)
        return result

    def _extract_results(self, strat: Any) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "initial_value": self.initial_cash,
            "final_value": self.cerebro.broker.getvalue(),
            "total_return": 0.0,
            "trades": [],
            "daily_pnl": [],
            "metrics": {},
        }
        result["total_return"] = (result["final_value"] - result["initial_value"]) / result["initial_value"]

        timereturn = strat.analyzers.timereturn.get_analysis()
        if timereturn:
            daily_data = []
            prev = self.initial_cash
            for dt_str, r in sorted(timereturn.items()):
                if r is not None:
                    cur = prev * (1 + r)
                    daily_data.append({
                        "date": dt_str, "total_value": cur,
                        "pnl": cur - prev, "pnl_pct": r * 100,
                    })
                    prev = cur
            result["daily_pnl"] = daily_data

        ra = strat.analyzers.returns.get_analysis()
        result["metrics"]["total_return"] = ra.get("rtot", 0)
        result["metrics"]["annualized_return"] = ra.get("rnorm", 0)

        sa = strat.analyzers.sharpe.get_analysis()
        result["metrics"]["sharpe_ratio"] = sa.get("sharperatio", 0)

        da = strat.analyzers.drawdown.get_analysis()
        result["metrics"]["max_drawdown"] = da.get("max", {}).get("drawdown", 0)
        result["metrics"]["max_drawdown_duration"] = da.get("max", {}).get("len", 0)

        ta = strat.analyzers.trades.get_analysis()
        if ta:
            tt = ta.get("total", {}).get("total", 0)
            won = ta.get("won", {}).get("total", 0)
            lost = ta.get("lost", {}).get("total", 0)
            result["metrics"]["total_trades"] = tt
            result["metrics"]["winning_trades"] = won
            result["metrics"]["losing_trades"] = lost
            result["metrics"]["win_rate"] = won / tt if tt > 0 else 0
            if "won" in ta and "pnl" in ta["won"]:
                result["metrics"]["avg_profit"] = ta["won"]["pnl"].get("average", 0)
            if "lost" in ta and "pnl" in ta["lost"]:
                result["metrics"]["avg_loss"] = ta["lost"]["pnl"].get("average", 0)

        if hasattr(strat, "get_trade_df"):
            tdf = strat.get_trade_df()
            if len(tdf) > 0:
                result["trades"] = tdf.to_dict("records")
        elif hasattr(strat, "trade_records") and len(strat.trade_records) > 0:
            result["trades"] = strat.trade_records

        m = result["metrics"]
        ap = m.get("avg_profit", 0)
        al = abs(m.get("avg_loss", 0))
        plr = ap / al if al > 0 else 0.0
        result["performance_metrics"] = PerformanceMetrics(
            total_return=result["total_return"],
            annual_return=m.get("annualized_return", 0),
            benchmark_return=0.0,
            excess_return=result["total_return"],
            sharpe_ratio=m.get("sharpe_ratio", 0),
            sortino_ratio=0.0,
            calmar_ratio=0.0,
            max_drawdown=m.get("max_drawdown", 0),
            max_drawdown_duration=m.get("max_drawdown_duration", 0),
            volatility=0.0,
            win_rate=m.get("win_rate", 0),
            profit_loss_ratio=plr,
            total_trades=m.get("total_trades", 0),
        )
        return result

    def _save_to_db(self, strategy_name: str, result: Dict[str, Any]) -> None:
        import uuid

        self.run_id = f"bt_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        conn = self._get_conn(read_only=False)
        try:
            conn.execute(
                """INSERT INTO backtest_run (run_id, strategy_name, strategy_params,
                   start_date, end_date, universe, benchmark, initial_capital, status)
                   VALUES (?, ?, '{}', ?, ?, 'custom', '000300.SH', ?, 'completed')""",
                [self.run_id, strategy_name,
                 self.start_date or date.today(), self.end_date or date.today(),
                 self.initial_cash],
            )

            if result["trades"]:
                tdf = pd.DataFrame(result["trades"])
                for col in ["code", "name", "commission", "industry", "market_cap_group"]:
                    if col not in tdf.columns:
                        tdf[col] = None
                if "datetime" not in tdf.columns and "date" in tdf.columns:
                    tdf["datetime"] = pd.to_datetime(tdf["date"])
                if "size" not in tdf.columns and "volume" in tdf.columns:
                    tdf["size"] = tdf["volume"]
                if "amount" not in tdf.columns and "price" in tdf.columns and "size" in tdf.columns:
                    tdf["amount"] = tdf["price"] * tdf["size"]
                tdf["id"] = range(len(tdf))
                tdf["run_id"] = self.run_id
                keep = ["id", "run_id", "datetime", "code", "name", "action", "price",
                        "size", "amount", "commission", "industry", "market_cap_group"]
                tdf = tdf[[c for c in keep if c in tdf.columns]]
                conn.execute("INSERT INTO backtest_trades BY NAME SELECT * FROM tdf")

            if result.get("daily_pnl"):
                ddf = pd.DataFrame(result["daily_pnl"])
                if not ddf.empty:
                    ddf["run_id"] = self.run_id
                    ddf["positions"] = None
                    ddf = ddf[["run_id", "date", "pnl", "pnl_pct", "total_value", "positions"]]
                    conn.execute("INSERT INTO backtest_daily_pnl BY NAME SELECT * FROM ddf")

            fm = {
                "annual_return": result["metrics"].get("annualized_return", 0),
                "total_return": result["total_return"],
                "max_drawdown": result["metrics"].get("max_drawdown", 0),
                "sharpe_ratio": result["metrics"].get("sharpe_ratio", 0),
                "win_rate": result["metrics"].get("win_rate", 0),
                "total_trades": result["metrics"].get("total_trades", 0),
                "avg_holding_days": 0,
            }
            conn.execute(
                """INSERT INTO backtest_performance (run_id, total_return, annual_return,
                   max_drawdown, sharpe_ratio, win_rate, total_trades, avg_holding_days)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [self.run_id, fm["total_return"], fm["annual_return"],
                 fm["max_drawdown"], fm["sharpe_ratio"], fm["win_rate"],
                 fm["total_trades"], fm["avg_holding_days"]],
            )
            logger.info(f"回测结果已保存，run_id: {self.run_id}")
        finally:
            conn.close()

    def _print_results(self, result: Dict[str, Any]) -> None:
        m = result.get("metrics", {})
        print("\n" + "=" * 50)
        print("回测结果")
        print("=" * 50)
        print(f"初始资金: {result['initial_value']:,.2f}")
        print(f"最终资金: {result['final_value']:,.2f}")
        print(f"总收益率: {result['total_return'] * 100:.2f}%")
        print(f"年化收益率: {(m.get('annualized_return') or 0) * 100:.2f}%")
        print(f"夏普比率: {m.get('sharpe_ratio') or 0:.2f}")
        print(f"最大回撤: {m.get('max_drawdown') or 0:.2f}%")
        print(f"交易次数: {m.get('total_trades', 0)}")
        print(f"胜率: {(m.get('win_rate', 0) or 0) * 100:.2f}%")
        print("=" * 50)

    def plot(self, **kwargs: Any) -> None:
        self.cerebro.plot(**kwargs)

    def get_run_id(self) -> Optional[str]:
        return self.run_id
