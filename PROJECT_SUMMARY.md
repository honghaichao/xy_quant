# xy_quant v2.1 系统总结

> 2026-07-20 更新 · 5 commits · 27 files · ~3,500 行

---

## 新能力

### 🤖 AI Agent 投研（Phase 1）
- DeepSeek 驱动的全自动股票分析：数据→3分析师并行→牛熊辩论→风控→交易信号
- 批量分析 + 调度集成（每晚 23:15 自动运行）
- 8 个 Bug 修复使系统从不可用到端到端可跑

### 🔗 实盘 Gateway（Phase 2）  
- 标准化网关抽象层：`IGateway` 接口 + 6 个数据模型
- `PaperGateway`（纸面盘）+ `GatewayManager`（订单分发）+ `QmtGateway`（真实券商）
- Mac 环境优雅降级，QMT 代码就位待 Windows 验证

### 🧬 AI 因子工厂（Phase 3）
- **Expression DSL**：14 个内置函数，AST 解析求值（`ts_delta(close,2)/close`）
- **GA Miner**：遗传算法自动挖因子（变异/交叉/IC 适应度，最高 0.3346）
- 因子注册表从 38→41（新增 3 个 GA 发现因子）

### 🔧 核心修复（Phase 4）
- S1 卖出信号从日均 41.5→6（阈值收紧 85%）
- 卖出仅对持仓股生效（防止虚假事件）
- multiprocessing fork→spawn（确保代码更新生效）

### 🎛️ 策略编辑器（Phase 5）
- 三 Tab 竖排布局：策略列表 → Monaco 编辑器（含回测跳转）→ 策略共振分析
- 新 API：`/api/strategy-editor/resonance`（多策略信号交叉）

---

## 系统快照

| 组件 | 状态 |
|------|------|
| 日线数据 | 778 万行, 2020-至今 |
| 分钟线 | 17.4 亿行, 2020-至今 |
| 信号事件 | 7,224 条 (买 3,910 / 卖 3,314) |
| 因子 | 41 注册, IC Top=0.23 |
| 持仓 | 13 只 (B1/B2/BLK/JQ) |
| Agent | 5 条分析记录 |
| 调度器 | 🟢 运行中 (14 jobs) |
| Dashboard | localhost:5004 |
