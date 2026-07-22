"""
Flask API - 股票分析接口

端到端分析入口:
  analyze_stock(symbol, trade_date, ...)

Agent 流水线:
  数据获取 → 3 分析师并行 → 牛熊研究员 → 辩论 → 研究经理 → 风控 → 交易信号 → 入库
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from typing import Any

# 确保 .env 在最早期加载
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agent.graph.trading_graph import TradingAgentsGraph
from agent.dataflows.stock_adapter import StockDataAdapter
from agent.dataflows.news.aggregator import NewsAggregator
from agent.adapters.result_adapter import ResultAdapter


# ═══════════════════════════════════════════════════════════════
# LLM 创建
# ═══════════════════════════════════════════════════════════════

def _create_deepseek_llm():
    """创建 DeepSeek LLM 适配器。"""
    from agent.llm_adapters.factory import create_llm_by_provider
    return create_llm_by_provider(
        provider="deepseek",
        model="deepseek-chat",
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
    )


def get_llm_adapter():
    """获取 LLM 适配器 — 优先 DeepSeek，失败→降级。"""
    try:
        llm = _create_deepseek_llm()
        # 快速可用性检查：如果没有 key，直接降级
        if llm is None or getattr(llm, "api_key", None) is None:
            return _create_fallback_llm("未配置 DEEPSEEK_API_KEY")
        return llm
    except Exception as e:
        return _create_fallback_llm(str(e))


def _create_fallback_llm(reason: str = ""):
    """降级 LLM — 打印原因，返回提示文本。"""

    class FallbackLLM:
        def __init__(self, r: str):
            self.reason = r

        def chat(self, messages):
            return (
                f"[Agent 降级模式] LLM 不可用（{self.reason}），无法完成 AI 分析。\n"
                "请检查 DEEPSEEK_API_KEY 环境变量或网络连接。"
            )

        @property
        def api_key(self):
            return None

    return FallbackLLM(reason)


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

class AnalysisError(Exception):
    """分析错误异常"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def analyze_stock(
    symbol: str,
    trade_date: str | None = None,
    *,
    include_memory: bool = False,
    llm=None,
    debug: bool = False,
) -> dict[str, Any]:
    """分析单只股票 — 端到端 Agent 流水线。

    Args:
        symbol: 股票代码，如 '600519'
        trade_date: 交易日期 'YYYY-MM-DD'，默认今天
        include_memory: 是否加载历史记忆（默认关，避免写锁冲突）
        llm: 外部注入的 LLM 实例，不传则自动创建
        debug: 打印详细日志

    Returns:
        {
            'success': bool,
            'run_id': str,
            'symbol': str,
            'trade_date': str,
            'final_decision': str,
            'confidence': float,
            'trading_signal': {...},
            'reports': {...},
            'partial': bool,          # True=部分分析成功，有降级
            'errors': [...],          # 降级/错误列表
        }
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    errors: list[str] = []
    partial = False

    # ---- LLM ----
    if llm is None:
        llm = get_llm_adapter()

    # ---- 数据获取 ----
    stock_adapter = StockDataAdapter()

    # 1) 行情数据（必需）
    price_data = None
    try:
        end_date = trade_date.replace("-", "")
        start_dt = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=180)
        start_date = start_dt.strftime("%Y%m%d")
        price_data = stock_adapter.get_market_data(symbol, start_date, end_date)
        if price_data is None or len(price_data) == 0:
            errors.append("行情数据为空")
    except Exception as e:
        errors.append(f"行情数据获取失败: {e}")

    if price_data is None or len(price_data) == 0:
        return {
            "success": False,
            "symbol": symbol,
            "trade_date": trade_date,
            "error": "行情数据获取失败",
            "errors": errors,
        }

    # 2) 新闻数据（非必需）
    news_list: list = []
    try:
        aggregator = NewsAggregator()
        result = aggregator.get_stock_news(symbol, limit=20)
        news_list = result.news_list if hasattr(result, "news_list") else []
    except Exception as e:
        errors.append(f"新闻获取失败: {e}")
        partial = True

    # 3) 基本面数据（非必需）
    fundamentals_data: dict[str, Any] = {}
    try:
        fundamentals_data = stock_adapter.get_fundamentals(symbol)
    except Exception as e:
        errors.append(f"基本面获取失败: {e}")
        partial = True

    # ---- Agent 工作流 ----
    try:
        graph = TradingAgentsGraph(
            llm=llm,
            selected_analysts=['market', 'news', 'fundamentals', 'intraday', 'moneyflow', 'deep_stock'],
            debug=debug,
            memory_manager=None,
            include_memory_context=False,
        )

        # Prepare new analysis inputs
        from datetime import date as _date
        intraday_text = ""
        moneyflow_text = ""
        financials_text = ""
        try:
            td = _date.today()
            if trade_date:
                td = _date.fromisoformat(trade_date)
            from agent.dataflows.markets.intraday import format_intraday_for_llm
            intraday_text = format_intraday_for_llm(symbol, td)
        except Exception as e:
            errors.append(f"盘中数据获取失败: {e}")
            partial = True

        try:
            from agent.dataflows.markets.moneyflow import format_money_flow_for_llm
            moneyflow_text = format_money_flow_for_llm(symbol)
        except Exception as e:
            errors.append(f"资金流数据获取失败: {e}")
            partial = True

        try:
            from agent.dataflows.financials import format_financials_for_llm
            financials_text = format_financials_for_llm(symbol)
        except Exception as e:
            errors.append(f"深度财务数据获取失败: {e}")
            partial = True

        result = graph.propagate(
            company_of_interest=symbol,
            trade_date=trade_date,
            price_data=price_data,
            news_list=news_list,
            fundamentals_data=fundamentals_data,
            intraday_text=intraday_text,
            moneyflow_text=moneyflow_text,
            financials_text=financials_text,
        )
    except Exception as e:
        errors.append(f"Agent 工作流异常: {e}")
        return {
            "success": False,
            "symbol": symbol,
            "trade_date": trade_date,
            "error": f"Agent 工作流异常: {e}",
            "errors": errors,
            "reports": {},
        }

    # ---- 后处理：研究经理 + 风控 + 交易信号 ----
    current_price = 0.0
    try:
        if price_data is not None and len(price_data) > 0:
            last = price_data.iloc[-1]
            current_price = float(last.get("close", 0))
    except Exception:
        pass

    try:
        from agent.research_manager.research_manager import ResearchManager
        from agent.risk_manager.risk_manager import RiskManager
        from agent.traders.trader import Trader
        from agent.base import AgentConfig

        # 研究经理
        try:
            rm = ResearchManager(AgentConfig(
                name="research", role="research_manager", llm_adapter=llm,
            ))
            research_result = rm.conduct_research(
                symbol,
                reports=result.get("reports", {}),
                research={
                    "bull_research": result.get("bull_research", ""),
                    "bear_research": result.get("bear_research", ""),
                },
            )
            result["research"] = research_result
        except Exception as e:
            errors.append(f"研究经理失败: {e}")
            partial = True
            research_result = {"recommendation": "观望", "confidence": 0.3}

        # 风控
        try:
            risk_mgr = RiskManager(AgentConfig(
                name="risk", role="risk_manager", llm_adapter=llm,
            ))
            risk_result = risk_mgr.assess_risk(
                investment_decision=research_result.get("recommendation", "观望"),
                confidence=research_result.get("confidence", 0.5),
                bull_research=result.get("bull_research", ""),
                bear_research=result.get("bear_research", ""),
                stock_code=symbol,
                current_price=current_price,
            )
            result["risk"] = risk_result
        except Exception as e:
            errors.append(f"风控评估失败: {e}")
            partial = True
            risk_result = {"risk_level": "MEDIUM", "risk_score": 0.5}

        # 交易信号
        try:
            trader = Trader()
            trading_signal = trader.generate_trading_signal(
                investment_decision=research_result.get("recommendation", "观望"),
                risk_assessment=risk_result,
                current_price=current_price,
                stock_code=symbol,
            )
            result["trading_signal"] = trading_signal
        except Exception as e:
            errors.append(f"交易信号生成失败: {e}")
            partial = True
            result["trading_signal"] = {"action": "HOLD", "reasoning": "信号生成失败"}
    except Exception as e:
        errors.append(f"后处理异常: {e}")
        partial = True

    # ---- 入库 ----
    result["symbol"] = symbol
    result["trade_date"] = trade_date
    result["errors"] = errors
    result["partial"] = partial

    run_id = ""
    try:
        result_adapter = ResultAdapter()
        run_id = result_adapter.save_analysis_result(symbol, trade_date, result)
    except Exception as e:
        errors.append(f"结果入库失败: {e}")
        partial = True

    result["run_id"] = run_id
    result["success"] = len(errors) == 0 or partial

    return result


# ═══════════════════════════════════════════════════════════════
# 查询接口
# ═══════════════════════════════════════════════════════════════

def get_analysis_history(
    symbol: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    offset: int = 0,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """获取分析历史"""
    try:
        result_adapter = ResultAdapter()
        return result_adapter.get_analysis_history(
            symbol=symbol, start_date=start_date, end_date=end_date,
            offset=offset, limit=limit,
        )
    except Exception as e:
        print(f"获取分析历史失败: {e}")
        return []


def get_analysis_result(run_id: str) -> dict[str, Any] | None:
    """获取指定分析结果"""
    try:
        result_adapter = ResultAdapter()
        return result_adapter.load_analysis_result(run_id)
    except Exception as e:
        print(f"获取分析结果失败: {e}")
        return None


def health_check() -> dict[str, Any]:
    """健康检查"""
    status: dict[str, Any] = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "components": {},
    }

    # 数据库
    try:
        result_adapter = ResultAdapter()
        db = result_adapter._get_db()
        if db:
            status["components"]["database"] = "ok"
        else:
            status["components"]["database"] = "failed"
            status["status"] = "degraded"
    except Exception:
        status["components"]["database"] = "failed"
        status["status"] = "degraded"

    # LLM
    try:
        llm = get_llm_adapter()
        if llm and getattr(llm, "api_key", None) is not None:
            status["components"]["llm"] = "ok"
        else:
            status["components"]["llm"] = "degraded"
            status["status"] = "degraded"
    except Exception:
        status["components"]["llm"] = "failed"
        status["status"] = "degraded"

    return status
