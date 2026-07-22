"""资金流分析师 — 分析主力资金动向、北向资金、板块资金对比。

继承 BaseAgent 模式，接收资金流数据，输出资金面分析报告。
"""

from __future__ import annotations

from typing import Any

from agent.base import AgentConfig, BaseAgent


class MoneyFlowAnalyst(BaseAgent):
    """资金流分析师 — 分析主力/北向/板块资金动向。"""

    def __init__(self, config: AgentConfig):
        super().__init__(config)

    def _create_system_prompt(self) -> str:
        return """你是一名A股资金流分析师，专注于主力资金动向解读。

你的分析框架：

1. **个股主力动向**
   - 近 5/10/20 日主力净流入趋势：持续流入/流出/震荡
   - 主力净流入占比（main_inflow_pct）> 5% 为积极信号
   - 超大单 vs 大单 vs 中单 vs 小单 结构分析
   - 主力在吸筹（量增价稳）还是在出货（量增价跌）

2. **盘中实时资金流**
   - 当日盘中主力净流入/流出方向
   - 与近期趋势是否一致
   - 大单动向（超大单+大单净额)

3. **板块资金流对比**
   - 该股所属板块的资金流排名
   - 板块整体是否受主力青睐
   - 该股在板块内的资金流相对强度

4. **信号解读**
   - 主力持续流入 + 股价横盘 = 吸筹信号
   - 主力大幅流出 + 股价上涨 = 拉高出货
   - 散户净流入为主 + 主力净流出 = 危险信号
   - 北向或主力+散户同向流入 = 共振信号

输出要求：
- 主力资金态度（积极/中性/消极）
- 给出资金流评分（1-10）
- 明确是否有吸筹/出货迹象
- 具体操作建议（如：可关注/需回避）"""

    def _process_input(self, inputs: dict[str, Any]) -> str:
        """处理资金流数据输入。"""
        moneyflow_text = inputs.get("moneyflow_text", "")
        symbol = inputs.get("symbol", "")

        lines = [
            f"请分析股票 {symbol} 的资金流情况：",
            "",
            moneyflow_text,
            "",
            "请给出：",
            "1) 主力资金态度（积极/中性/消极）及评分（1-10）",
            "2) 吸筹/出货信号判断",
            "3) 板块资金流对比分析",
            "4) 具体操作建议",
        ]
        return "\n".join(lines)
