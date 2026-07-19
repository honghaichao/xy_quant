# xy_quant P0 数据补全实施计划

> **For Hermes:** 先补计划，按计划执行；如发现脚本缺失，先补脚本，再补数据。

**目标：** 补齐 2020-01-01 至最新交易日的 P0 数据覆盖，先明确缺哪些数据、用哪些脚本补全、脚本缺失时先创建脚本。

**架构：** 以“数据域 → 存储后端 → 补数脚本 → 验证脚本”为主线推进。市场行情类数据写 DuckDB，元数据/资金流类写 PostgreSQL；所有补数动作必须幂等，并以交易日覆盖率作为验收标准。计划先盘点缺口，再为每个缺口绑定唯一入口脚本，最后补充统一验证脚本。

**Tech Stack：** Python 3.14.3, DuckDB, PostgreSQL, pandas, pytest, loguru, Tushare/现有数据源适配层。

---

### Task 1: 盘点 P0 缺口清单

**Objective:** 明确哪些表、哪些交易日缺失，形成可执行的补数清单。

**Files:**
- Read: `PLAN.md`
- Read: `data_store/market.duckdb`
- Read: PostgreSQL `quant` 库中的 meta/fund 表
- Read: `logs/minute_bar_progress.jsonl`
- Read: `tests/unit/test_data_api_coverage.py`

**Step 1: 读取现有覆盖率结果**

确认以下表的缺口：
- DuckDB: `daily_bar`, `daily_basic`, `adj_factor`, `index_daily`, `limit_list`, `minute_bar`
- PostgreSQL: `stock_suspend`, `top_list`, `margin_detail`, `hk_hold`, `stock_money_flow`, `concept_money_flow`, `industry_money_flow`

**Step 2: 输出缺口格式**

每张表输出：
- 表名
- 存储后端
- 已覆盖交易日数 / 总交易日数
- 缺失交易日样本
- 是否允许跳过（默认否）

**Step 3: 生成补数优先级**

优先级建议：
1. 交易日全量覆盖的基础表
2. 资金流/两融/港股通等 meta 表
3. 仍在跑的 minute_bar 或大表重跑修复

**验证标准：** 缺口清单可直接转成脚本任务，不再依赖口头描述。

---

### Task 2: 盘点现有补数脚本入口

**Objective:** 找到能直接复用的补数脚本，避免重复造轮子。

**Files:**
- Search: `scripts/*.py`
- Search: `data/**`
- Search: `tools/**`（若存在）
- Search: `tests/**`

**Step 1: 列出现有脚本入口**

重点确认是否已有：
- `scripts/full_load.py`
- `scripts/init_db.py`
- `scripts/orchestration.py`
- `scripts/init_foundations.py`
- minute_bar 专用补数脚本
- money_flow / margin / hk_hold / suspend / top_list 专用补数脚本

**Step 2: 分类脚本能力**

每个脚本标记为：
- 可直接调用
- 需要增加命令行参数
- 需要拆分/重构
- 完全缺失，需新建

**验证标准：** 得到“表 → 脚本入口 → 是否缺失”的一一对应表。

---

### Task 3: 为缺失的数据域补脚本

**Objective:** 如果某些表没有独立补数脚本，先补一个稳定入口脚本。

**Files:**
- Create or modify: `scripts/full_load.py`
- Create or modify: `scripts/backfill_market.py`
- Create or modify: `scripts/backfill_meta.py`
- Create or modify: `scripts/backfill_money_flow.py`
- Create or modify: `scripts/backfill_minute_bar.py`
- Modify: 现有数据更新/调度模块

**Step 1: 定义脚本职责边界**

- `backfill_market.py`：`daily_bar`, `daily_basic`, `adj_factor`, `index_daily`, `limit_list`
- `backfill_minute_bar.py`：`minute_bar` 的交易日补数
- `backfill_meta.py`：`stock_suspend`, `top_list`, `margin_detail`, `hk_hold`
- `backfill_money_flow.py`：`stock_money_flow`, `concept_money_flow`, `industry_money_flow`
- `full_load.py`：统一调度入口，按任务顺序调用上述脚本

**Step 2: 规定脚本参数**

每个脚本建议统一支持：
- `--start-date YYYY-MM-DD`
- `--end-date YYYY-MM-DD`
- `--tables ...`
- `--dry-run`
- `--force`

**Step 3: 定义幂等要求**

脚本必须支持重复运行不产生重复行；已存在交易日数据只更新不重复插入。

**验证标准：** 每个缺口数据域都有一个明确可调用的脚本入口。

---

### Task 4: 若脚本缺失，先补脚本测试

**Objective:** 给新脚本或新增入口写最小测试，防止补数入口再度漂移。

**Files:**
- Create: `tests/unit/test_backfill_market.py`
- Create: `tests/unit/test_backfill_meta.py`
- Create: `tests/unit/test_backfill_money_flow.py`
- Create: `tests/unit/test_backfill_minute_bar.py`
- Modify: 现有脚本测试文件

**Step 1: 写脚本存在性测试**

测试内容包括：
- 脚本可被 `python scripts/xxx.py --help` 正常解析
- 必要参数存在
- 入口函数可导入

**Step 2: 写路由测试**

验证表名能路由到正确补数脚本，例如：
- `stock_suspend` → `backfill_meta.py`
- `minute_bar` → `backfill_minute_bar.py`
- `stock_money_flow` → `backfill_money_flow.py`

**验证标准：** 新脚本先有测试，再进入实现。

---

### Task 5: 补统一验证脚本

**Objective:** 让补数完成后可以自动检查“还缺多少”并输出最终状态。

**Files:**
- Create or modify: `scripts/check_p0_coverage.py`
- Modify: `tests/unit/test_data_api_coverage.py`

**Step 1: 定义验证输出**

脚本输出每张表：
- 覆盖交易日数
- 缺失交易日数
- 缺失样本
- 总结是否通过 P0

**Step 2: 绑定验收规则**

规则以交易日覆盖为准，不以表是否存在为准；DuckDB 与 PostgreSQL 分别检查对应表。

**验证标准：** 一条命令可重跑并确认是否已补齐。

---

### Task 6: 按缺口顺序执行补数

**Objective:** 根据缺口清单逐表补数，直到覆盖率达标。

**Files:**
- Run: 对应的 backfill 脚本
- Verify: `scripts/check_p0_coverage.py`

**Step 1: 先补基础市场表**

依次补：`daily_bar` → `daily_basic` → `adj_factor` → `index_daily` → `limit_list`

**Step 2: 再补资金与元数据表**

依次补：`stock_suspend` → `top_list` → `margin_detail` → `hk_hold` → `stock_money_flow` → `concept_money_flow` → `industry_money_flow`

**Step 3: 最后处理 `minute_bar`**

仅在日志或验证显示仍有缺口时重跑，并按交易日范围补齐。

**验证标准：** 所有目标表达到 2020-01-01 至最新交易日全覆盖。

---

### Task 7: 最终回归验证

**Objective:** 给出可复核的最终结论。

**Files:**
- Run: `scripts/check_p0_coverage.py`
- Run: `pytest tests/unit/test_data_api_coverage.py -v`

**Step 1: 运行覆盖率检查**

确认每张表缺失交易日为 0。

**Step 2: 运行测试**

确认补数脚本、路由和验证逻辑都通过。

**Step 3: 输出最终报告**

列出：
- 已补哪些数据
- 用了哪些脚本
- 哪些脚本是新补的
- 最终是否满足 P0

**验证标准：** 结果可直接给用户做阶段汇报。

---

### 执行顺序

1. 先做 Task 1 和 Task 2，得到缺口与脚本现状
2. 对缺失脚本先做 Task 3 和 Task 4
3. 再执行 Task 6 补数
4. 最后执行 Task 5 和 Task 7 验证
