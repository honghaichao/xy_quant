"""风控监控 — 每日组合风控检查。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import duckdb

from config.settings import settings
from risk.rules import RiskEngine, RiskLimits
from utils.logger import get_logger

logger = get_logger("risk_monitor")

DB_PATH = str(settings.duckdb_path)


class RiskMonitor:
    """Daily risk monitoring utility."""

    def __init__(self, engine: RiskEngine | None = None):
        self.engine = engine or RiskEngine()

    def check_daily(
        self,
        trade_date: date,
        portfolio_id: str | None = None,
    ) -> dict[str, Any]:
        """Run all risk checks for a trading day.

        Returns risk report with violations, stop-loss triggers, VaR, drawdown.
        """
        # Load positions
        positions = self._load_positions()

        # Compute portfolio value
        total_capital = sum(p.get("current_value", 0) for p in positions.values())

        # Load returns for VaR
        returns = self._load_portfolio_returns(trade_date, days=252)

        # Load equity curve for drawdown
        equity = self._load_equity_curve(trade_date)

        report = self.engine.run_portfolio_risk_check(
            positions=positions,
            total_capital=total_capital,
            returns=returns,
            equity_curve=equity,
        )

        # Add summary
        report["trade_date"] = trade_date.isoformat()
        report["total_capital"] = total_capital
        report["position_count"] = len(positions)

        # Log report
        n_violations = len(report.get("violations", []))
        n_stops = len(report.get("stop_loss_triggers", []))
        status = "⚠️" if n_violations or n_stops else "✅"
        logger.info(
            f"{status} Risk check {trade_date}: "
            f"capital={total_capital:,.0f}, positions={len(positions)}, "
            f"violations={n_violations}, stops={n_stops}, "
            f"VaR95={report.get('vaR_95','?')}"
        )

        return report

    def _load_positions(self) -> dict[str, dict[str, Any]]:
        """Load current positions from DuckDB."""
        conn = duckdb.connect(DB_PATH, read_only=True)
        try:
            rows = conn.execute(
                """SELECT code, name, strategy, buy_price, current_price,
                          shares, status, profit_loss, profit_pct
                   FROM positions WHERE status = 'holding'"""
            ).fetchall()
        except Exception:
            return {}
        finally:
            conn.close()

        positions = {}
        for row in rows:
            code = row[0]
            positions[code] = {
                "code": code,
                "name": row[1],
                "strategy": row[2],
                "entry_price": float(row[3] or 0),
                "current_price": float(row[4] or 0),
                "shares": int(row[5] or 0),
                "current_value": float(row[4] or 0) * int(row[5] or 0),
                "status": row[6],
                "pnl": float(row[7] or 0),
                "pnl_pct": float(row[8] or 0),
            }

        return positions

    def _load_portfolio_returns(self, trade_date: date, days: int = 252):
        """Load portfolio daily returns from DuckDB."""
        conn = duckdb.connect(DB_PATH, read_only=True)
        try:
            df = conn.execute(
                """SELECT date, (total_value - LAG(total_value) OVER (ORDER BY date))
                           / NULLIF(LAG(total_value) OVER (ORDER BY date), 0) AS ret
                   FROM portfolio_daily
                   WHERE date >= ? AND date <= ?
                   ORDER BY date""",
                [(trade_date - timedelta(days=days)).isoformat(), trade_date.isoformat()],
            ).fetchdf()
        except Exception:
            return None
        finally:
            conn.close()

        if df.empty:
            return None
        return df["ret"].dropna()

    def _load_equity_curve(self, trade_date: date):
        """Load portfolio equity curve from DuckDB."""
        conn = duckdb.connect(DB_PATH, read_only=True)
        try:
            df = conn.execute(
                """SELECT date, total_value
                   FROM portfolio_daily
                   WHERE date <= ?
                   ORDER BY date""",
                [trade_date.isoformat()],
            ).fetchdf()
        except Exception:
            return None
        finally:
            conn.close()

        if df.empty:
            return None
        return df["total_value"]
