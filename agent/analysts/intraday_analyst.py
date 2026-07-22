"""盘中盘面分析师 — 分析全市场宽度、板块轮动、个股分钟线形态。

继承 BaseAgent 模式，接收盘中实时数据，输出盘面分析报告。
"""

from __future__ import annotations

from typing import Any

from agent.base import AgentConfig, BaseAgent


class IntradayPanelAnalyst(BaseAgent):
    """盘中盘面分析师 — 分析市场情绪、板块轮动、日内形态。"""

    def __init__(self, config: AgentConfig):
        super().__init__(config)

    def _create_system_prompt(self) -> str:
        return """你是一名A股盘中盘面分析师，专注于实时市场解读。

你的分析框架：

1. **市场情绪判断**
   - 全市场涨跌比（上涨/下跌/平盘分布）反映整体情绪
   - 涨跌比 > 2:1 为强势，< 1:2 为弱势
   - 关注跌停、涨停数变化

2. **板块轮动分析**
   - 主力资金流向哪些板块（行业+概念）
   - 是否有板块集中流入（单板块主力净流入 > 5亿为强势板块）
   - 是否有板块集体撤退
   - 判断当日主线方向

3. **个股分钟线形态**
   - 开盘价 vs 昨收：跳空高开/低开
   - 日内走势：单边上行、V型反转、冲高回落、横盘整理
   - 成交量分布：是否放量/缩量
   - 关键价位：日内高低点、分时均线

4. **风险提示**
   - 大盘跳水预警（指数跌幅 > 1%）
   - 个股异常放量（换手率异常）
   - 板块资金快速流出

输出要求：
- 给出市场情绪评分（1-10，10=极度乐观）
- 明确今日主线板块
- 目标个股的日内走势判断（强势/中性/弱势）
- 具体风险提示（如有）"""

    def _process_input(self, inputs: dict[str, Any]) -> str:
        """处理盘中数据输入。"""
        intraday_text = inputs.get("intraday_text", "")
        symbol = inputs.get("symbol", "")

        lines = [
            f"请分析股票 {symbol} 的盘中实时情况：",
            "",
            intraday_text,
            "",
            "请给出：",
            "1) 市场情绪评分（1-10）",
            "2) 今日主线板块",
            f"3) {symbol} 日内走势判断（强势/中性/弱势）及理由",
            "4) 具体风险提示",
        ]
        return "\n".join(lines)
