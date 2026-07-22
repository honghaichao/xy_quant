"""深度个股分析师 — 分析财务质量、估值合理性与行业竞争力。

继承 BaseAgent 模式，接收深度财务+估值数据，输出个股基本面报告。
"""

from __future__ import annotations

from typing import Any

from agent.base import AgentConfig, BaseAgent


class DeepStockAnalyst(BaseAgent):
    """深度个股分析师 — 财务质量、估值、行业竞争力分析。"""

    def __init__(self, config: AgentConfig):
        super().__init__(config)

    def _create_system_prompt(self) -> str:
        return """你是一名A股深度个股分析师，专注于财务报表分析与企业估值。

你的分析框架：

1. **财务健康度评估**
   - 盈利能力：ROE/ROA/毛利率/净利率 的绝对值和趋势
   - 成长性：营收同比/净利润同比 是否持续增长
   - 现金流质量：经营现金流 vs 净利润（经营现金流 > 净利润 = 健康）
   - 偿债能力：资产负债率、流动比率、速动比率
   - 资产质量：商誉占比、应收账款周转

2. **估值分析**
   - 当前 PE/PB 与同业可比公司的对比
   - PE 是否在同行业处于合理区间
   - 市值规模在行业内的排名
   - 成长性（营收增速）能否支撑当前估值

3. **行业竞争力**
   - 在行业内的市场份额（总市值排名）
   - 毛利率 vs 行业平均（高毛利率 = 竞争壁垒）
   - ROE 是否高于行业平均

4. **投资建议**
   - 综合财务健康度 + 估值合理性 → 评分
   - 识别财务造假风险信号（营收增长但现金流萎缩等）
   - 给出安全边际建议

输出要求：
- 财务健康度评分（1-10）
- 估值合理性判断（低估/合理/高估）
- 核心竞争优势分析（1-2句话）
- 具体投资建议"""

    def _process_input(self, inputs: dict[str, Any]) -> str:
        """处理深度财务数据输入。"""
        financials_text = inputs.get("financials_text", "")
        symbol = inputs.get("symbol", "")

        lines = [
            f"请对股票 {symbol} 进行深度基本面分析：",
            "",
            financials_text,
            "",
            "请给出：",
            "1) 财务健康度评分（1-10）及核心依据",
            "2) 当前估值判断（低估/合理/高估）及同业对比分析",
            "3) 核心竞争优势（1-2句话）",
            "4) 投资建议（强烈买入/买入/观望/卖出/强烈卖出）",
        ]
        return "\n".join(lines)
