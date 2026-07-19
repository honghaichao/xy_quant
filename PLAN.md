# 个人量化系统建设计划书 (Hermes 严格执行版 v6)

> 本文档是 Hermes 的**唯一执行宪法**。违反本文档的任何代码必须拒绝合并。

---

## 〇、防跑偏机制(最高优先级,先读这一章)

### 0.1 三道硬门禁(Hard Gate)

**Phase 转换必须通过门禁**,Hermes 不能自行跨越:

```
[Phase A 工程初始化] ──Gate0──> [Phase B 业务开发]
[P0 数据层]         ──Gate1──> [P1 复盘报告]
[P1 复盘报告]       ──Gate2──> [P2 因子引擎]
[P2 因子引擎]       ──Gate3──> [P3 回测引擎]
[P3 回测引擎]       ──Gate4──> [P4 策略+风控+调度]
[P4 策略+风控+调度] ──Gate5──> [P5 Web 服务]
[P5 Web 服务]       ──Gate6──> [P6 实盘交易]
```

**通过门禁的条件**(全部满足才算通过):
1. 该阶段所有验收标准 100% 满足
2. 单元测试通过且覆盖率 ≥ 70%
3. `ruff` / `mypy` 无警告
4. 代码 review 由用户人工确认(Hermes 输出 `[GATE_REQUEST]` 标记并停止)
5. 用户回复 `[GATE_PASS]` 才能进入下一阶段

**Hermes 看到 `[GATE_REQUEST]` 必须停下,不允许自行进入下一阶段。**

### 0.2 禁止行为清单(违反立即回滚)

Hermes **绝对不允许**:

1. ❌ 修改本文档定义的表名、字段名、字段类型、主键
2. ❌ 修改本文档定义的接口签名(参数名、参数顺序、返回类型)
3. ❌ 添加文档没要求的功能(比如自作主张加缓存、加日志、加 metrics)
4. ❌ 跳过未实现的依赖(用 `TODO` / `pass` / `NotImplementedError` 占位)
5. ❌ 在代码中硬编码 token、账号、密码、文件路径
6. ❌ 用 `print` 输出(必须用 `loguru.logger`)
7. ❌ 写裸 `except:` 或 `except Exception:`(必须捕获具体异常类)
8. ❌ 用字符串拼接 SQL(必须用参数化查询)
9. ❌ 在没有 `[GATE_PASS]` 时进入下一 Phase
10. ❌ 替你做"产品决策"(命名取舍、功能取舍要问用户,不要自己拍板)
11. ❌ 自己往 `.env` 里填真实值(只能写 `.env.example` 模板)
12. ❌ 安装文档没列出的第三方库

### 0.3 偏航识别信号(出现立即停下并问)

如果发现以下情况,Hermes 必须**立即停止编码**,输出 `[ALERT]` 标记并询问用户:

- ⚠️ 文档定义的字段在数据源里不存在
- ⚠️ 文档定义的接口无法满足某需求
- ⚠️ 第三方库版本不兼容
- ⚠️ 性能基准达不到要求
- ⚠️ 单元测试反复失败
- ⚠️ 出现循环依赖
- ⚠️ 需要新增配置项
- ⚠️ 需要新增第三方库
- ⚠️ 用户的需求与文档冲突

### 0.4 自检清单(每次 commit 前必跑)

Hermes 提交代码前必须自查并在 commit message 末尾贴出结果:

```
[SELF_CHECK]
[✓] 所有函数有 type hints
[✓] 所有 public 函数有 docstring
[✓] ruff 无警告
[✓] mypy 无警告
[✓] 单元测试通过 (pytest)
[✓] 覆盖率 ≥ 70% (pytest-cov)
[✓] 没有 TODO/FIXME/XXX 占位
[✓] 没有 print(用 loguru)
[✓] 没有硬编码 token/path
[✓] 没有裸 except
[✓] 接口签名与文档一致
[✓] 表结构与文档一致
```

**任何一项 ✗,代码不允许提交。**

### 0.5 通信协议

Hermes 与用户的固定标记:
- `[GATE_REQUEST]` - 请求通过门禁
- `[GATE_PASS]` - 用户批准通过(由用户输入)
- `[ALERT]` - 偏航或冲突告警
- `[QUESTION]` - 需要用户决策
- `[BLOCKED]` - 被外部依赖阻塞
- `[DONE]` - 子模块完成

---

## 一、面向接口架构(核心设计原则)

### 1.1 总原则

**所有外部依赖通过抽象接口注入,业务代码只依赖接口不依赖实现。**

```
业务代码 ──依赖──> 抽象接口 (ABC)
                    ↑
                    │实现
                    │
              具体实现 (Tushare/AKShare/QMT/...)
```

### 1.2 强制接口分层

每一类外部依赖必须定义抽象接口(`abc.ABC`),具体实现注册到工厂:

| 接口类型 | 抽象基类 | 当前实现 | 未来可换 |
|---|---|---|---|
| 数据源 | `IDataSource` | `TushareDataSource`, `AkshareDataSource` | 万得/聚宽/JQData/Choice |
| 行情存储 | `IMarketStore` | `DuckDBMarketStore` | ClickHouse/Arctic/Parquet |
| 元数据存储 | `IMetaStore` | `PostgresMetaStore` | MySQL/SQLite |
| 缓存 | `ICache` | `RedisCache` | Memcached/InMemory |
| 任务调度 | `IScheduler` | `APSchedulerImpl` | Airflow/Celery |
| 通知 | `INotifier` | `EmailNotifier`, `DingTalkNotifier` | 飞书/企微/Slack |
| 行情订阅 | `IQuoteSubscriber` | `QmtQuoteSubscriber`(P6) | CTP/IB |
| 交易网关 | `ITradeGateway` | `BacktestGateway`, `QmtGateway`(P6) | Ptrade/CTP/IB |
| 报告渲染 | `IReportRenderer` | `HTMLRenderer`, `ImageRenderer` | PDF/Word |
| LLM 服务 | `ILLMProvider` | `LocalRuleProvider` | Claude/GPT/Gemini |

### 1.3 接口实现模板

每个接口必须遵守如下模板:

```python
# 1. 定义接口(在 interfaces/ 下)
from abc import ABC, abstractmethod

class IDataSource(ABC):
    """数据源抽象接口。所有数据源必须实现此接口。"""
    
    name: str  # 类属性,数据源标识
    
    @abstractmethod
    def fetch_daily_bar(self, ...) -> pd.DataFrame:
        """获取日线行情。"""

# 2. 具体实现(在 data/source/ 下)
class TushareDataSource(IDataSource):
    name = "tushare"
    def fetch_daily_bar(self, ...) -> pd.DataFrame:
        ...

# 3. 工厂注册(在 data/source/factory.py)
DATA_SOURCE_REGISTRY: dict[str, type[IDataSource]] = {
    "tushare": TushareDataSource,
    "akshare": AkshareDataSource,
}

def get_data_source(name: str) -> IDataSource:
    return DATA_SOURCE_REGISTRY[name]()

# 4. 业务代码用法(只依赖接口)
def update_daily_bar(source: IDataSource, store: IMarketStore) -> int:
    df = source.fetch_daily_bar(...)
    return store.upsert("daily_bar", df)
```

**业务代码绝不直接 `import tushare` 或 `import akshare`,只能通过工厂拿到 `IDataSource` 实例。**

### 1.4 字段标准化契约

由于不同数据源字段名不一致,**适配器层必须把所有数据源的输出统一到本文档定义的标准字段**(见第六章表结构)。

例如 AKShare 涨停板返回中文字段,适配器内必须映射:
- `代码` → `ts_code`
- `名称` → `name`
- `最新价` → `close`
- `涨跌幅` → `pct_chg`

字段映射表必须写在适配器顶部,作为常量定义。

---

## 二、Phase A:工程初始化(Hermes 第一步必做)

> **此阶段不写任何业务代码**,只搭工程骨架。完成后请求 Gate0。

### 2.1 创建 Git 仓库

```bash
mkdir quant_system && cd quant_system
git init
git branch -M main
```

`.gitignore` 必须包含:
```
__pycache__/
*.pyc
.venv/
.env
data_store/
logs/
reports/
.pytest_cache/
.ruff_cache/
.mypy_cache/
htmlcov/
.coverage
*.duckdb
*.duckdb.wal
.idea/
.vscode/
```

### 2.2 创建目录骨架

```
quant_system/
├── interfaces/                  # 抽象接口层(核心!)
│   ├── __init__.py
│   ├── data_source.py           # IDataSource
│   ├── market_store.py          # IMarketStore
│   ├── meta_store.py            # IMetaStore
│   ├── cache.py                 # ICache
│   ├── scheduler.py             # IScheduler
│   ├── notifier.py              # INotifier
│   ├── quote_subscriber.py      # IQuoteSubscriber (P6)
│   ├── trade_gateway.py         # ITradeGateway (P4 起)
│   ├── report_renderer.py       # IReportRenderer
│   └── llm_provider.py          # ILLMProvider
├── config/
│   ├── __init__.py
│   ├── settings.py
│   └── review_rules.yaml        # P1 判定阈值
├── data/                        # P0
│   ├── __init__.py
│   ├── source/
│   │   ├── __init__.py
│   │   ├── factory.py
│   │   ├── tushare_source.py
│   │   └── akshare_source.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── factory.py
│   │   ├── duckdb_store.py
│   │   ├── pg_store.py
│   │   └── redis_cache.py
│   ├── updater/
│   ├── validator/
│   ├── adjust/
│   └── api.py
├── review/                      # P1
│   ├── __init__.py
│   ├── collector.py
│   ├── analyzer.py
│   ├── narrative.py
│   ├── main.py
│   ├── llm/
│   │   └── local_rule_provider.py
│   ├── renderer/
│   │   ├── __init__.py
│   │   ├── factory.py
│   │   ├── html_renderer.py
│   │   ├── image_renderer.py
│   │   └── templates/
│   └── templates/
├── factor/                      # P2
├── backtest/                    # P3
├── strategy/                    # P4
├── gateway/                     # P4 (P6 扩展)
├── risk/                        # P4
├── scheduler/                   # P4
├── api/                         # P5
├── ui/                          # P5
├── live/                        # P6
├── utils/
│   ├── __init__.py
│   ├── logger.py
│   ├── exception.py
│   ├── calendar.py
│   ├── rate_limiter.py
│   └── retry.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── scripts/
│   ├── init_db.py
│   ├── full_load.py
│   ├── run_review.py
│   └── demo/
├── deploy/
│   ├── docker-compose.yml
│   ├── Dockerfile
│   └── setup.sh
├── docs/
│   ├── interfaces.md
│   ├── tables.md
│   └── conventions.md
├── .env.example                 # 模板,Hermes 不准填值
├── .gitignore
├── pyproject.toml
├── README.md
└── PLAN.md                      # 本文档
```

### 2.3 `pyproject.toml`(Hermes 严格按此安装,不准加库)

```toml
[project]
name = "quant_system"
version = "0.1.0"
description = "Personal quantitative trading system"
requires-python = ">=3.11,<3.13"
dependencies = [
    # 数据源
    "tushare>=1.4.0",
    "akshare>=1.15.0",
    # 存储
    "duckdb>=1.0.0",
    "psycopg[binary]>=3.2.0",
    "redis>=5.0.0",
    "sqlalchemy>=2.0.0",
    # 数据处理
    "polars>=1.0.0",
    "pandas>=2.2.0",
    "numpy>=1.26.0",
    "pyarrow>=15.0.0",
    # 配置
    "pydantic>=2.6.0",
    "pydantic-settings>=2.2.0",
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0.0",
    # 工具
    "loguru>=0.7.2",
    "tenacity>=8.2.3",
    "apscheduler>=3.10.4",
    # 报告(P1)
    "jinja2>=3.1.0",
    "matplotlib>=3.8.0",
    "pillow>=10.0.0",
    "playwright>=1.42.0",
]

[project.optional-dependencies]
factor = ["scipy>=1.13.0", "scikit-learn>=1.4.0", "numba>=0.59.0"]
backtest = ["quantstats>=0.0.62"]
parallel = ["ray[default]>=2.10.0"]
api = ["fastapi>=0.110.0", "uvicorn>=0.29.0", "websockets>=12.0"]
ui = ["streamlit>=1.33.0", "plotly>=5.20.0"]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=5.0.0",
    "pytest-mock>=3.12.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.0",
    "black>=24.0.0",
    "mypy>=1.10.0",
    "pre-commit>=3.7.0",
]

[tool.ruff]
line-length = 100
target-version = "py311"
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM", "PL"]
ignore = ["E501", "PLR0913"]

[tool.ruff.per-file-ignores]
"tests/*" = ["PLR2004"]

[tool.black]
line-length = 100
target-version = ["py311"]

[tool.mypy]
python_version = "3.11"
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "integration: integration tests (require external services)",
    "slow: slow tests",
]
addopts = "-v --strict-markers"
```

### 2.4 `.env.example`(Hermes 创建,**严禁填真实值**)

```ini
# ====================================================
# 量化系统环境配置
# 1. 复制为 .env: cp .env.example .env
# 2. 由用户填写实际值
# 3. Hermes 不允许填写任何真实值
# ====================================================

# ---- Tushare(必填,用户自己填) ----
TUSHARE_TOKEN=

# ---- DuckDB(行情库,本地文件) ----
DUCKDB_PATH=./data_store/market.duckdb

# ---- PostgreSQL(基本面库) ----
PG_HOST=localhost
PG_PORT=5432
PG_USER=quant
PG_PASSWORD=
PG_DATABASE=quant

# ---- Redis(缓存) ----
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# ---- 限频(每分钟最大请求数) ----
TUSHARE_RATE_LIMIT_PER_MIN=200
AKSHARE_RATE_LIMIT_PER_MIN=300

# ---- 日志 ----
LOG_LEVEL=INFO
LOG_DIR=./logs

# ---- 数据源选择(支持切换) ----
PRIMARY_DATA_SOURCE=tushare
FALLBACK_DATA_SOURCE=akshare

# ---- 通知(可选) ----
NOTIFIER_TYPE=                    # email / dingtalk / wechat
EMAIL_SMTP_HOST=
EMAIL_SMTP_PORT=587
EMAIL_USERNAME=
EMAIL_PASSWORD=
EMAIL_TO=
DINGTALK_WEBHOOK=

# ---- QMT(P6 才用) ----
QMT_PATH=
QMT_ACCOUNT_ID=
QMT_SESSION_ID=

# ---- LLM(P1 复盘可选) ----
LLM_PROVIDER=local_rule           # local_rule / claude / gpt
LLM_API_KEY=
LLM_API_BASE=
```

### 2.5 `config/settings.py`(Hermes 必须严格按此实现)

```python
"""全局配置。从 .env 加载,不允许硬编码任何敏感值。"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # Tushare
    tushare_token: str = ""
    
    # DuckDB
    duckdb_path: str = "./data_store/market.duckdb"
    
    # PostgreSQL
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "quant"
    pg_password: str = ""
    pg_database: str = "quant"
    
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    
    # 限频
    tushare_rate_limit_per_min: int = 200
    akshare_rate_limit_per_min: int = 300
    
    # 日志
    log_level: str = "INFO"
    log_dir: str = "./logs"
    
    # 数据源
    primary_data_source: str = "tushare"
    fallback_data_source: str = "akshare"
    
    # 通知
    notifier_type: str = ""
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_username: str = ""
    email_password: str = ""
    email_to: str = ""
    dingtalk_webhook: str = ""
    
    # QMT
    qmt_path: str = ""
    qmt_account_id: str = ""
    qmt_session_id: str = ""
    
    # LLM
    llm_provider: str = "local_rule"
    llm_api_key: str = ""
    llm_api_base: str = ""
    
    @property
    def pg_dsn(self) -> str:
        return (
            f"postgresql://{self.pg_user}:{self.pg_password}@"
            f"{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )
    
    @property
    def log_dir_path(self) -> Path:
        p = Path(self.log_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
```

### 2.6 Docker Compose 启动外部依赖

`deploy/docker-compose.yml`:

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16-alpine
    container_name: quant_postgres
    environment:
      POSTGRES_USER: quant
      POSTGRES_PASSWORD: ${PG_PASSWORD:-quant}
      POSTGRES_DB: quant
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U quant"]
      interval: 5s
      timeout: 5s
      retries: 5
  
  redis:
    image: redis:7-alpine
    container_name: quant_redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
  redis_data:
```

### 2.7 启动脚本

`deploy/setup.sh`:

```bash
#!/usr/bin/env bash
set -e

echo "==> Step 1: 创建 Python 虚拟环境"
python3.11 -m venv .venv
source .venv/bin/activate

echo "==> Step 2: 安装依赖"
pip install --upgrade pip
pip install -e ".[dev,factor,backtest,api,ui]"
playwright install chromium

echo "==> Step 3: 启动 PostgreSQL + Redis"
cd deploy
docker compose up -d
cd ..

echo "==> Step 4: 等待数据库就绪"
sleep 10

echo "==> Step 5: 检查 .env"
if [ ! -f .env ]; then
    echo "ERROR: .env 不存在,请先 cp .env.example .env 并填入 token"
    exit 1
fi

echo "==> Step 6: 初始化数据库表"
python scripts/init_db.py

echo "==> 完成!可以开始数据加载: python scripts/full_load.py"
```

### 2.8 README 模板

`README.md` 必须包含:
- 项目简介
- 快速开始(`bash deploy/setup.sh`)
- 配置说明(指向 `.env.example`)
- 模块说明
- 开发约定(指向 `docs/conventions.md`)

### 2.9 ✅ Gate0 验收标准

Phase A 完成必须满足:

- [ ] 项目目录骨架完整,所有空 `__init__.py` 已创建
- [ ] `pyproject.toml` 完整,字段无误
- [ ] `.env.example` 创建,**所有敏感字段为空**
- [ ] `.env` 不存在(由用户创建)
- [ ] `config/settings.py` 实现,可从 `.env` 加载
- [ ] `interfaces/` 下所有抽象接口骨架已定义
- [ ] `deploy/docker-compose.yml` 能成功启动 PostgreSQL + Redis
- [ ] `deploy/setup.sh` 可执行
- [ ] `utils/logger.py` 实现(loguru)
- [ ] `utils/rate_limiter.py` 实现(令牌桶)
- [ ] `utils/retry.py` 实现(tenacity 装饰器)
- [ ] `utils/exception.py` 实现(自定义异常类)
- [ ] `docs/conventions.md` 写明开发约定
- [ ] 用户能跑通 `pip install -e ".[dev]"` 不报错
- [ ] 用户能跑通 `docker compose up -d` 不报错
- [ ] `pytest` 可运行(即使没有测试也不报错)

**Hermes 完成 Phase A 后输出 `[GATE_REQUEST] Phase A 完成,请确认进入 P0`,等待用户回复 `[GATE_PASS]`。**

---

## 三、抽象接口定义(Hermes 必须照抄)

> 这一章是接口契约。Hermes 在 Phase A 必须先定义所有接口骨架,具体实现留给后续 Phase。

### 3.1 `interfaces/data_source.py`

```python
"""数据源抽象接口。所有数据源(Tushare/AKShare/Wind/...)必须实现。"""
from abc import ABC, abstractmethod
from datetime import date
import pandas as pd


class IDataSource(ABC):
    """数据源接口。"""
    
    name: str  # 子类必须设置类属性,如 "tushare"
    
    # ==================== 行情 ====================
    
    @abstractmethod
    def fetch_daily_bar(
        self,
        ts_code: str | list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """日线行情。
        
        Returns:
            列:ts_code, trade_date, open, high, low, close, pre_close,
               change, pct_chg, vol, amount
        """
    
    @abstractmethod
    def fetch_minute_bar(
        self,
        ts_code: str,
        start_date: date,
        end_date: date,
        freq: str = "1min",
    ) -> pd.DataFrame:
        """分钟线行情。"""
    
    @abstractmethod
    def fetch_adj_factor(
        self,
        ts_code: str | list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """复权因子。"""
    
    @abstractmethod
    def fetch_daily_basic(
        self,
        ts_code: str | list[str] | None = None,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """每日指标。"""
    
    @abstractmethod
    def fetch_index_daily(
        self,
        ts_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """指数日线。"""
    
    # ==================== 涨跌停 ====================
    
    @abstractmethod
    def fetch_limit_pool(
        self, trade_date: date, kind: str = "U"  # U/D/Z
    ) -> pd.DataFrame:
        """涨跌停池。"""
    
    # ==================== 元数据 ====================
    
    @abstractmethod
    def fetch_stock_basic(self) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_trade_calendar(
        self, start_date: date, end_date: date
    ) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_stock_suspend(
        self, trade_date: date | None = None, ts_code: str | None = None
    ) -> pd.DataFrame: ...
    
    # ==================== 财务 ====================
    
    @abstractmethod
    def fetch_income(
        self, ts_code: str,
        start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_balancesheet(
        self, ts_code: str,
        start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_cashflow(
        self, ts_code: str,
        start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_fina_indicator(
        self, ts_code: str,
        start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_dividend(self, ts_code: str) -> pd.DataFrame: ...
    
    # ==================== 资金面 ====================
    
    @abstractmethod
    def fetch_top_list(self, trade_date: date) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_margin_detail(self, trade_date: date) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_stk_holdertrade(
        self, ts_code: str | None = None, ann_date: date | None = None
    ) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_hk_hold(
        self, trade_date: date | None = None, ts_code: str | None = None
    ) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_concept_money_flow(self, trade_date: date) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_industry_money_flow(self, trade_date: date) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_stock_money_flow(self, trade_date: date) -> pd.DataFrame: ...
    
    # ==================== 板块成分 ====================
    
    @abstractmethod
    def fetch_concept_list(self) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_concept_member(self, concept_code: str) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_industry_list(self) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_industry_member(self, industry_code: str) -> pd.DataFrame: ...
    
    @abstractmethod
    def fetch_index_weight(
        self, index_code: str, trade_date: date | None = None
    ) -> pd.DataFrame: ...
    
    # ==================== 能力声明 ====================
    
    def supports(self, capability: str) -> bool:
        """声明该数据源支持哪些数据。
        
        子类必须重写,声明能力清单。
        例:Tushare 2000 积分不支持 limit_pool/minute_bar
        """
        return False
```

### 3.2 `interfaces/market_store.py`

```python
"""行情存储接口。"""
from abc import ABC, abstractmethod
from datetime import date
import pandas as pd


class IMarketStore(ABC):
    """行情数据存储接口(主要面向时序数据)。"""
    
    @abstractmethod
    def init_schema(self) -> None: ...
    
    @abstractmethod
    def upsert(self, table: str, df: pd.DataFrame) -> int: ...
    
    @abstractmethod
    def query(self, sql: str, params: dict | None = None) -> pd.DataFrame: ...
    
    @abstractmethod
    def execute(self, sql: str, params: dict | None = None) -> int: ...
    
    @abstractmethod
    def get_last_date(
        self, table: str, ts_code: str | None = None
    ) -> date | None: ...
    
    @abstractmethod
    def count(self, table: str, where: str | None = None) -> int: ...
    
    @abstractmethod
    def close(self) -> None: ...
```

### 3.3 `interfaces/meta_store.py`

```python
"""元数据存储接口(关系型,基本面/财务)。"""
from abc import ABC, abstractmethod
import pandas as pd


class IMetaStore(ABC):
    @abstractmethod
    def init_schema(self) -> None: ...
    
    @abstractmethod
    def upsert(self, table: str, df: pd.DataFrame) -> int: ...
    
    @abstractmethod
    def query(self, sql: str, params: dict | None = None) -> pd.DataFrame: ...
    
    @abstractmethod
    def execute(self, sql: str, params: dict | None = None) -> int: ...
    
    @abstractmethod
    def close(self) -> None: ...
```

### 3.4 `interfaces/cache.py`

```python
"""缓存接口。"""
from abc import ABC, abstractmethod
from typing import Any


class ICache(ABC):
    @abstractmethod
    def get(self, key: str) -> Any | None: ...
    
    @abstractmethod
    def set(self, key: str, value: Any, ttl: int = 300) -> None: ...
    
    @abstractmethod
    def delete(self, key: str) -> None: ...
    
    @abstractmethod
    def exists(self, key: str) -> bool: ...
```

### 3.5 `interfaces/notifier.py`

```python
"""通知接口。"""
from abc import ABC, abstractmethod
from pathlib import Path


class INotifier(ABC):
    @abstractmethod
    def send_text(self, title: str, content: str) -> bool: ...
    
    @abstractmethod
    def send_file(self, title: str, content: str, file_path: Path) -> bool: ...
    
    @abstractmethod
    def send_image(self, title: str, content: str, image_path: Path) -> bool: ...
```

### 3.6 `interfaces/report_renderer.py`

```python
"""报告渲染接口。"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class IReportRenderer(ABC):
    @abstractmethod
    def render(self, data: dict[str, Any], output_path: Path) -> Path: ...
```

### 3.7 `interfaces/llm_provider.py`

```python
"""LLM 服务接口(P1 复盘文案可选用)。"""
from abc import ABC, abstractmethod


class ILLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str: ...
    
    @abstractmethod
    def is_available(self) -> bool: ...
```

### 3.8 `interfaces/scheduler.py`

```python
"""任务调度接口。"""
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime


class IScheduler(ABC):
    @abstractmethod
    def add_cron_job(
        self, func: Callable, cron_expr: str, job_id: str, **kwargs
    ) -> None: ...
    
    @abstractmethod
    def add_date_job(
        self, func: Callable, run_date: datetime, job_id: str, **kwargs
    ) -> None: ...
    
    @abstractmethod
    def remove_job(self, job_id: str) -> None: ...
    
    @abstractmethod
    def start(self) -> None: ...
    
    @abstractmethod
    def shutdown(self) -> None: ...
```

### 3.9 其他接口

`interfaces/quote_subscriber.py`(P6)、`interfaces/trade_gateway.py`(P4 起)同样定义骨架,具体方法在对应 Phase 时再补全。

---

## 四、可用资源边界

| 资源 | 用途 | 限制 |
|---|---|---|
| Tushare Pro 2000 积分 | 主数据源 | 覆盖日线、分钟线、财务、指数、北向等历史数据;部分接口频次限制 |
| AKShare | 辅数据源 | 免费,接口偶发不稳定;主要作为 Tushare 不覆盖或异常时的补充源,字段为中文需映射 |
| QMT (xtquant) | P6 实盘 + 盘中行情 | Windows only;实时回调约 3 秒一次 |

### 数据职责矩阵

```
┌─────────────────────┬──────────┬─────────┬─────────┐
│   数据类型           │ Tushare  │ AKShare │  QMT    │
├─────────────────────┼──────────┼─────────┼─────────┤
│ 日线历史             │   主     │   备    │   ✗     │
│ 复权因子             │   主     │   -     │   ✗     │
│ 每日指标             │   主     │   -     │   ✗     │
│ 财务三表             │   主     │   -     │   ✗     │
│ 财务指标             │   主     │   -     │   ✗     │
│ 分红送股             │   主     │   -     │   ✗     │
│ 分钟线历史           │   主     │   备    │   ✗     │
│ 涨停板/炸板          │   ✗      │   主    │   ✗     │
│ 板块资金流           │   ✗      │   主    │   ✗     │
│ 个股资金流           │   ✗      │   主    │   ✗     │
│ 概念/行业板块成分    │   备     │   主    │   ✗     │
│ 龙虎榜               │   主     │   备    │   ✗     │
│ 融资融券             │   主     │   -     │   ✗     │
│ 股东增减持           │   主     │   -     │   ✗     │
│ 北向资金(历史)       │   主     │   -     │   ✗     │
│ 北向资金(实时)       │   ✗      │   主    │   ✗     │
│ 指数日线/成分        │   主     │   -     │   ✗     │
│ 实时 Tick (P6)       │   ✗      │   -     │   主    │
│ 实盘下单 (P6)        │   ✗      │   ✗     │   主    │
└─────────────────────┴──────────┴─────────┴─────────┘
```

---

## 五、新优先级路线(复盘报告提前)

```
P0  数据层
     ├─ 数据源适配器 (Tushare + AKShare,实现 IDataSource)
     ├─ 存储层 (DuckDB + PostgreSQL + Redis)
     ├─ 增量更新调度
     ├─ 数据校验
     ├─ 复权处理
     └─ 统一数据 API
                ↓ Gate1
P1  每日复盘报告生成器(数据齐了立即可做)
     ├─ 数据采集器
     ├─ 规则分析器
     ├─ 文案生成器
     └─ 报告渲染器 (HTML / 长图 / PDF)
                ↓ Gate2
P2  因子引擎
P3  回测引擎
P4  策略引擎 + 风控 + 调度
P5  Web 服务 (FastAPI + Streamlit)
P6  实盘交易 (QMT)
```

**P1 提前理由**:仅依赖 P0 数据,不依赖因子和回测,数据齐了立刻能产生价值。

---

## 六、表结构(完整版,Hermes 必须严格按此建表)

### 6.1 DuckDB 行情库

#### `daily_bar` 日线行情(不复权)
```sql
CREATE TABLE IF NOT EXISTS daily_bar (
    ts_code        VARCHAR  NOT NULL,
    trade_date     DATE     NOT NULL,
    open           DOUBLE,
    high           DOUBLE,
    low            DOUBLE,
    close          DOUBLE,
    pre_close      DOUBLE,
    change         DOUBLE,
    pct_chg        DOUBLE,
    vol            DOUBLE,
    amount         DOUBLE,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_bar_date ON daily_bar(trade_date);
```

#### `adj_factor` 复权因子
```sql
CREATE TABLE IF NOT EXISTS adj_factor (
    ts_code     VARCHAR NOT NULL,
    trade_date  DATE    NOT NULL,
    adj_factor  DOUBLE  NOT NULL,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, trade_date)
);
```

#### `daily_basic` 每日指标
```sql
CREATE TABLE IF NOT EXISTS daily_basic (
    ts_code            VARCHAR NOT NULL,
    trade_date         DATE    NOT NULL,
    close              DOUBLE,
    turnover_rate      DOUBLE,
    turnover_rate_f    DOUBLE,
    volume_ratio       DOUBLE,
    pe                 DOUBLE,
    pe_ttm             DOUBLE,
    pb                 DOUBLE,
    ps                 DOUBLE,
    ps_ttm             DOUBLE,
    dv_ratio           DOUBLE,
    dv_ttm             DOUBLE,
    total_share        DOUBLE,
    float_share        DOUBLE,
    free_share         DOUBLE,
    total_mv           DOUBLE,
    circ_mv            DOUBLE,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_basic_date ON daily_basic(trade_date);
```

#### `minute_bar` 分钟线
```sql
CREATE TABLE IF NOT EXISTS minute_bar (
    ts_code     VARCHAR    NOT NULL,
    datetime    TIMESTAMP  NOT NULL,
    freq        VARCHAR    NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    vol         DOUBLE,
    amount      DOUBLE,
    updated_at  TIMESTAMP  DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, datetime, freq)
);
CREATE INDEX IF NOT EXISTS idx_minute_bar_dt ON minute_bar(datetime);
```

#### `index_daily` 指数日线
```sql
CREATE TABLE IF NOT EXISTS index_daily (
    ts_code     VARCHAR NOT NULL,
    trade_date  DATE    NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    pre_close   DOUBLE,
    change      DOUBLE,
    pct_chg     DOUBLE,
    vol         DOUBLE,
    amount      DOUBLE,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, trade_date)
);
```

#### `limit_list` 涨跌停板
```sql
CREATE TABLE IF NOT EXISTS limit_list (
    trade_date     DATE    NOT NULL,
    ts_code        VARCHAR NOT NULL,
    name           VARCHAR,
    close          DOUBLE,
    pct_chg        DOUBLE,
    amount         DOUBLE,
    limit_amount   DOUBLE,
    float_mv       DOUBLE,
    total_mv       DOUBLE,
    turnover_ratio DOUBLE,
    fd_amount      DOUBLE,
    first_time     VARCHAR,
    last_time      VARCHAR,
    open_times     INTEGER,
    up_stat        VARCHAR,
    limit_times    INTEGER,
    "limit"        VARCHAR,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, ts_code)
);
CREATE INDEX IF NOT EXISTS idx_limit_list_date ON limit_list(trade_date);
```

### 6.2 PostgreSQL 元数据库

#### `stock_basic` 股票基础信息
```sql
CREATE TABLE IF NOT EXISTS stock_basic (
    ts_code        VARCHAR(20) PRIMARY KEY,
    symbol         VARCHAR(10) NOT NULL,
    name           VARCHAR(50) NOT NULL,
    area           VARCHAR(20),
    industry       VARCHAR(50),
    fullname       VARCHAR(100),
    market         VARCHAR(20),
    exchange       VARCHAR(10),
    list_status    VARCHAR(2),
    list_date      DATE,
    delist_date    DATE,
    is_hs          VARCHAR(2),
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_stock_basic_industry ON stock_basic(industry);
CREATE INDEX IF NOT EXISTS idx_stock_basic_market ON stock_basic(market);
```

#### `trade_calendar` 交易日历
```sql
CREATE TABLE IF NOT EXISTS trade_calendar (
    exchange       VARCHAR(10) NOT NULL,
    cal_date       DATE NOT NULL,
    is_open        SMALLINT NOT NULL,
    pretrade_date  DATE,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (exchange, cal_date)
);
```

#### `stock_suspend` 停复牌
```sql
CREATE TABLE IF NOT EXISTS stock_suspend (
    ts_code        VARCHAR(20) NOT NULL,
    trade_date     DATE NOT NULL,
    suspend_type   VARCHAR(2) NOT NULL,
    suspend_timing VARCHAR(50),
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, trade_date, suspend_type)
);
```

#### `income` 利润表
```sql
CREATE TABLE IF NOT EXISTS income (
    ts_code            VARCHAR(20) NOT NULL,
    end_date           DATE NOT NULL,
    ann_date           DATE,
    f_ann_date         DATE,
    report_type        VARCHAR(10) NOT NULL,
    comp_type          VARCHAR(10),
    basic_eps          DOUBLE PRECISION,
    diluted_eps        DOUBLE PRECISION,
    total_revenue      DOUBLE PRECISION,
    revenue            DOUBLE PRECISION,
    operate_profit     DOUBLE PRECISION,
    total_profit       DOUBLE PRECISION,
    n_income           DOUBLE PRECISION,
    n_income_attr_p    DOUBLE PRECISION,
    raw                JSONB,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, end_date, report_type)
);
CREATE INDEX IF NOT EXISTS idx_income_end ON income(end_date);
```

#### `balancesheet` 资产负债表
```sql
CREATE TABLE IF NOT EXISTS balancesheet (
    ts_code             VARCHAR(20) NOT NULL,
    end_date            DATE NOT NULL,
    ann_date            DATE,
    f_ann_date          DATE,
    report_type         VARCHAR(10) NOT NULL,
    total_assets        DOUBLE PRECISION,
    total_liab          DOUBLE PRECISION,
    total_hldr_eqy_inc_min_int DOUBLE PRECISION,
    total_cur_assets    DOUBLE PRECISION,
    total_cur_liab      DOUBLE PRECISION,
    inventories         DOUBLE PRECISION,
    accounts_receiv     DOUBLE PRECISION,
    money_cap           DOUBLE PRECISION,
    raw                 JSONB,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, end_date, report_type)
);
```

#### `cashflow` 现金流量表
```sql
CREATE TABLE IF NOT EXISTS cashflow (
    ts_code              VARCHAR(20) NOT NULL,
    end_date             DATE NOT NULL,
    ann_date             DATE,
    f_ann_date           DATE,
    report_type          VARCHAR(10) NOT NULL,
    n_cashflow_act       DOUBLE PRECISION,
    n_cashflow_inv_act   DOUBLE PRECISION,
    n_cash_flows_fnc_act DOUBLE PRECISION,
    c_inf_fr_operate_a   DOUBLE PRECISION,
    c_paid_goods_s       DOUBLE PRECISION,
    free_cashflow        DOUBLE PRECISION,
    raw                  JSONB,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, end_date, report_type)
);
```

#### `fina_indicator` 财务指标
```sql
CREATE TABLE IF NOT EXISTS fina_indicator (
    ts_code           VARCHAR(20) NOT NULL,
    end_date          DATE NOT NULL,
    ann_date          DATE,
    roe               DOUBLE PRECISION,
    roa               DOUBLE PRECISION,
    gross_margin      DOUBLE PRECISION,
    op_of_gr          DOUBLE PRECISION,
    netprofit_margin  DOUBLE PRECISION,
    debt_to_assets    DOUBLE PRECISION,
    current_ratio     DOUBLE PRECISION,
    quick_ratio       DOUBLE PRECISION,
    raw               JSONB,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, end_date)
);
```

#### `dividend` 分红送股
```sql
CREATE TABLE IF NOT EXISTS dividend (
    ts_code        VARCHAR(20) NOT NULL,
    end_date       DATE NOT NULL,
    ann_date       DATE,
    div_proc       VARCHAR(20) NOT NULL,
    stk_div        DOUBLE PRECISION,
    stk_bo_rate    DOUBLE PRECISION,
    stk_co_rate    DOUBLE PRECISION,
    cash_div       DOUBLE PRECISION,
    cash_div_tax   DOUBLE PRECISION,
    record_date    DATE,
    ex_date        DATE,
    pay_date       DATE,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, end_date, div_proc)
);
```

#### `top_list` 龙虎榜
```sql
CREATE TABLE IF NOT EXISTS top_list (
    trade_date     DATE NOT NULL,
    ts_code        VARCHAR(20) NOT NULL,
    name           VARCHAR(50),
    close          DOUBLE PRECISION,
    pct_change     DOUBLE PRECISION,
    turnover_rate  DOUBLE PRECISION,
    amount         DOUBLE PRECISION,
    l_sell         DOUBLE PRECISION,
    l_buy          DOUBLE PRECISION,
    l_amount       DOUBLE PRECISION,
    net_amount     DOUBLE PRECISION,
    net_rate       DOUBLE PRECISION,
    amount_rate    DOUBLE PRECISION,
    float_values   DOUBLE PRECISION,
    reason         VARCHAR(200) NOT NULL,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, ts_code, reason)
);
```

#### `margin_detail` 融资融券明细
```sql
CREATE TABLE IF NOT EXISTS margin_detail (
    trade_date     DATE NOT NULL,
    ts_code        VARCHAR(20) NOT NULL,
    name           VARCHAR(50),
    rzye           DOUBLE PRECISION,
    rqye           DOUBLE PRECISION,
    rzmre          DOUBLE PRECISION,
    rqyl           DOUBLE PRECISION,
    rzche          DOUBLE PRECISION,
    rqchl          DOUBLE PRECISION,
    rqmcl          DOUBLE PRECISION,
    rzrqye         DOUBLE PRECISION,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, ts_code)
);
```

#### `stk_holdertrade` 股东增减持
```sql
CREATE TABLE IF NOT EXISTS stk_holdertrade (
    ts_code        VARCHAR(20) NOT NULL,
    ann_date       DATE NOT NULL,
    holder_name    VARCHAR(200) NOT NULL,
    holder_type    VARCHAR(10),
    in_de          VARCHAR(10) NOT NULL,
    change_vol     DOUBLE PRECISION,
    change_ratio   DOUBLE PRECISION,
    after_share    DOUBLE PRECISION,
    after_ratio    DOUBLE PRECISION,
    avg_price      DOUBLE PRECISION,
    total_share    DOUBLE PRECISION,
    begin_date     DATE,
    close_date     DATE,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, ann_date, holder_name, in_de)
);
```

#### `hk_hold` 北向持股
```sql
CREATE TABLE IF NOT EXISTS hk_hold (
    trade_date     DATE NOT NULL,
    ts_code        VARCHAR(20) NOT NULL,
    name           VARCHAR(50),
    vol            DOUBLE PRECISION,
    ratio          DOUBLE PRECISION,
    exchange       VARCHAR(10) NOT NULL,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, ts_code, exchange)
);
```

#### `concept_member` 概念板块成分
```sql
CREATE TABLE IF NOT EXISTS concept_member (
    concept_code   VARCHAR(20) NOT NULL,
    concept_name   VARCHAR(100) NOT NULL,
    ts_code        VARCHAR(20) NOT NULL,
    in_date        DATE NOT NULL,
    out_date       DATE,
    is_active      SMALLINT DEFAULT 1,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (concept_code, ts_code, in_date)
);
CREATE INDEX IF NOT EXISTS idx_concept_member_ts ON concept_member(ts_code);
```

#### `industry_member` 行业板块成分
```sql
CREATE TABLE IF NOT EXISTS industry_member (
    industry_code  VARCHAR(20) NOT NULL,
    industry_name  VARCHAR(100) NOT NULL,
    ts_code        VARCHAR(20) NOT NULL,
    in_date        DATE NOT NULL,
    out_date       DATE,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (industry_code, ts_code, in_date)
);
```

#### `index_weight` 指数成分权重
```sql
CREATE TABLE IF NOT EXISTS index_weight (
    index_code     VARCHAR(20) NOT NULL,
    ts_code        VARCHAR(20) NOT NULL,
    trade_date     DATE NOT NULL,
    weight         DOUBLE PRECISION,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (index_code, ts_code, trade_date)
);
```

#### `concept_money_flow` 概念板块资金流(P1 复盘必需)
```sql
CREATE TABLE IF NOT EXISTS concept_money_flow (
    trade_date       DATE NOT NULL,
    concept_code     VARCHAR(20) NOT NULL,
    concept_name     VARCHAR(100) NOT NULL,
    pct_chg          DOUBLE PRECISION,
    main_inflow      DOUBLE PRECISION,
    main_inflow_pct  DOUBLE PRECISION,
    super_inflow     DOUBLE PRECISION,
    big_inflow       DOUBLE PRECISION,
    mid_inflow       DOUBLE PRECISION,
    small_inflow     DOUBLE PRECISION,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, concept_code)
);
CREATE INDEX IF NOT EXISTS idx_concept_mf_date ON concept_money_flow(trade_date);
```

#### `industry_money_flow` 行业板块资金流(P1 复盘必需)
```sql
CREATE TABLE IF NOT EXISTS industry_money_flow (
    trade_date       DATE NOT NULL,
    industry_code    VARCHAR(20) NOT NULL,
    industry_name    VARCHAR(100) NOT NULL,
    pct_chg          DOUBLE PRECISION,
    main_inflow      DOUBLE PRECISION,
    main_inflow_pct  DOUBLE PRECISION,
    super_inflow     DOUBLE PRECISION,
    big_inflow       DOUBLE PRECISION,
    mid_inflow       DOUBLE PRECISION,
    small_inflow     DOUBLE PRECISION,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, industry_code)
);
CREATE INDEX IF NOT EXISTS idx_industry_mf_date ON industry_money_flow(trade_date);
```

#### `stock_money_flow` 个股资金流(P1 复盘必需)
```sql
CREATE TABLE IF NOT EXISTS stock_money_flow (
    trade_date       DATE NOT NULL,
    ts_code          VARCHAR(20) NOT NULL,
    name             VARCHAR(50),
    pct_chg          DOUBLE PRECISION,
    main_inflow      DOUBLE PRECISION,
    main_inflow_pct  DOUBLE PRECISION,
    super_inflow     DOUBLE PRECISION,
    big_inflow       DOUBLE PRECISION,
    mid_inflow       DOUBLE PRECISION,
    small_inflow     DOUBLE PRECISION,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, ts_code)
);
CREATE INDEX IF NOT EXISTS idx_stock_mf_date ON stock_money_flow(trade_date);
```

#### `data_update_log` 数据更新日志
```sql
CREATE TABLE IF NOT EXISTS data_update_log (
    id             BIGSERIAL PRIMARY KEY,
    table_name     VARCHAR(50) NOT NULL,
    source         VARCHAR(20) NOT NULL,
    update_type    VARCHAR(20) NOT NULL,
    start_date     DATE,
    end_date       DATE,
    rows_affected  INTEGER,
    status         VARCHAR(20) NOT NULL,
    error_msg      TEXT,
    started_at     TIMESTAMP NOT NULL,
    finished_at    TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_update_log_table ON data_update_log(table_name, started_at DESC);
```

#### `data_quality_report` 数据质量报告
```sql
CREATE TABLE IF NOT EXISTS data_quality_report (
    id             BIGSERIAL PRIMARY KEY,
    report_date    DATE NOT NULL,
    table_name     VARCHAR(50) NOT NULL,
    check_type     VARCHAR(50) NOT NULL,
    check_result   VARCHAR(20) NOT NULL,
    details        JSONB,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_quality_report ON data_quality_report(report_date, table_name);
```

---

## 七、数据运维入口设计(关键!Hermes 必须严格按此实现)

### 7.1 设计原则

**所有数据更新通过 `data/updater/` 模块完成。脚本只是触发入口,不写业务逻辑。**

```
触发层(scripts/)              调度层(data/updater/)        执行层(data/source/, storage/)
─────────────────              ───────────────────          ─────────────────────────────
full_load_*.py    (全量)  ┐
update_*.py       (增量)  ├──> updater 模块 ──────────────> IDataSource + IMarketStore/IMetaStore
run_scheduler.py  (调度)  │
update_all.py     (编排)  ┘
```

**Hermes 严格规则**:
- ❌ 不允许在 `scripts/*.py` 里写 SQL、写循环拉数据
- ❌ 不允许在 `data/source/` 或 `data/storage/` 里写"是全量还是增量"的判断
- ✅ 业务逻辑全部封装在 `data/updater/` 的几个 `XxxUpdater` 类里
- ✅ 脚本只做:解析 CLI 参数 → 实例化 Updater → 调用 `update()` → 打日志退出
- ✅ 所有脚本提供 `run()` 函数(无参,从 settings/默认值取参数),供调度器直接调用

### 7.2 配置文件分层(关键!)

```
.env                              # 敏感配置 (gitignore,用户手动填)
└── TUSHARE_TOKEN, PG_PASSWORD, REDIS_PASSWORD, DINGTALK_WEBHOOK 等

config/
├── settings.yaml                 # 业务配置 (进 git)
│   └── 限频、路径、数据源选择、日志级别、首次加载起始日期等
├── scheduler_jobs.yaml           # 调度配置 (进 git)
│   └── 任务定义、cron 表达式、是否启用
└── review_rules.yaml             # P1 复盘判定阈值 (进 git)
```

**`settings.yaml` 示例**:

```yaml
data_source:
  primary: tushare
  fallback: akshare

rate_limit:
  tushare_per_min: 200
  akshare_per_min: 300

paths:
  duckdb: ./data_store/market.duckdb
  log_dir: ./logs
  report_dir: ./reports

bootstrap:
  daily_bar_start_date: "2014-01-01"
  minute_bar_start_date: "2023-01-01"
  finance_start_date: "2010-01-01"
  limit_list_start_date: "2020-01-01"
  money_flow_start_date: "2020-01-01"

logging:
  level: INFO
  rotation: "100 MB"
  retention: "30 days"

retry:
  max_attempts: 3
  initial_delay: 1
  max_delay: 30

notification:
  on_failure: true
  on_success: false
  channel: dingtalk    # email / dingtalk / wechat / none
```

**Hermes 必须**:
- 敏感配置(token、密码)只放 `.env`,**禁止**放 YAML
- 业务参数(限频、起始日期、路径)只放 `settings.yaml`,**禁止**写死在代码里
- 调度时间只放 `scheduler_jobs.yaml`,**禁止**在 Python 里硬编码 cron 表达式
- 加载顺序:`.env` → `settings.yaml`,后者引用前者的占位符

### 7.3 脚本拆分(全量与日常完全分离)

#### 7.3.1 全量初始化脚本(`scripts/full_load_*.py`)

**用途**:首次部署时跑,把历史数据一次性拉到本地。

**特点**:
- 起始日期从 `config/settings.yaml` 的 `bootstrap` 节读取
- **不接受 `--date` 参数**(这就是与 update 的本质区别)
- 接受 `--start --end --ts_codes` 用于精细控制
- 跑得慢、耗时长、**只跑一次**

**清单**:

| 脚本 | 数据源 | 默认起始日期 |
|---|---|---|
| `full_load_calendar.py` | Tushare | (全量) |
| `full_load_basic.py` | Tushare | (全量) |
| `full_load_daily_bar.py` | Tushare | 2014-01-01 |
| `full_load_adj_factor.py` | Tushare | 2014-01-01 |
| `full_load_daily_basic.py` | Tushare | 2014-01-01 |
| `full_load_index_daily.py` | Tushare | 2014-01-01 |
| `full_load_minute_bar.py` | Tushare | 2023-01-01 |
| `full_load_limit_list.py` | AKShare | 2020-01-01 |
| `full_load_money_flow.py` | AKShare | 2020-01-01 |
| `full_load_top_list.py` | Tushare | 2014-01-01 |
| `full_load_margin.py` | Tushare | 2014-01-01 |
| `full_load_hk_hold.py` | Tushare | 2017-01-01 |
| `full_load_suspend.py` | Tushare | 2014-01-01 |
| `full_load_finance.py` | Tushare | 2010-01-01 |
| `full_load_member.py` | AKShare | (全量) |
| `full_load_holdertrade.py` | Tushare | 2014-01-01 |
| `full_load_all.py` | 编排器 | 一键全量,按依赖顺序调用全部 |

**典型用法**:
```bash
# 首次部署一键全量
python scripts/full_load_all.py

# 单独全量某个表(失败重跑用)
python scripts/full_load_daily_bar.py

# 限定起始日期
python scripts/full_load_daily_bar.py --start 2018-01-01

# 限定股票(测试用)
python scripts/full_load_daily_bar.py --ts_codes 600519.SH,000001.SZ
```

#### 7.3.2 日常增量脚本(`scripts/update_*.py`)

**用途**:每日 / 每周 / 每月运维,只需指定日期。

**特点**:
- **接受 `--date` 参数**,默认最近一个交易日
- 不指定日期 = 跑昨天到今天(自动识别最后已更新日期)
- 跑得快、可重复、**频繁调用**
- 既可手动跑,也可调度器调

**清单**:

| 脚本 | 触发频率 | 默认行为 |
|---|---|---|
| `update_calendar.py` | 每周一次 | 拉未来一年的交易日历 |
| `update_basic.py` | 每周一次 | 拉股票列表(含新上市/退市) |
| `update_daily_bar.py` | 每个交易日 | 拉最近一个交易日 |
| `update_adj_factor.py` | 每个交易日 | 拉最近一个交易日 |
| `update_daily_basic.py` | 每个交易日 | 拉最近一个交易日 |
| `update_index_daily.py` | 每个交易日 | 拉最近一个交易日 |
| `update_limit_list.py` | 每个交易日 | 拉最近一个交易日 |
| `update_money_flow.py` | 每个交易日 | 拉最近一个交易日 |
| `update_top_list.py` | 每个交易日 | 拉最近一个交易日(T+1) |
| `update_margin.py` | 每个交易日 | 拉最近一个交易日(T+1) |
| `update_hk_hold.py` | 每个交易日 | 拉最近一个交易日 |
| `update_suspend.py` | 每个交易日 | 拉最近一个交易日 |
| `update_finance.py` | 每月一次 | 拉最近一个季度财报 |
| `update_member.py` | 每周一次 | 全量刷板块成分(变化少) |
| `update_holdertrade.py` | 每月一次 | 拉最近一月公告 |
| `update_all.py` | 编排器 | 一键调用所有日常更新 |

**典型用法**:
```bash
# 拉最近一个交易日(默认)
python scripts/update_daily_bar.py

# 拉指定日期
python scripts/update_daily_bar.py --date 2026-05-07

# 拉日期范围(补数用)
python scripts/update_daily_bar.py --start 2026-05-01 --end 2026-05-07

# 强制覆盖(默认 upsert,加 --force 强制重拉)
python scripts/update_daily_bar.py --date 2025-01-15 --force

# 一键日常更新
python scripts/update_all.py
python scripts/update_all.py --date 2026-05-07
```

#### 7.3.3 编排器(`update_all.py` / `full_load_all.py`)

**作用**:按依赖顺序调用一组脚本。

**两个编排器都必须实现**:

`scripts/full_load_all.py` —— 全量编排:
```
1.  full_load_calendar
2.  full_load_basic
3.  full_load_daily_bar       ┐
4.  full_load_adj_factor      │  并行(线程池,Tushare 限频内)
5.  full_load_daily_basic     │
6.  full_load_index_daily     ┘
7.  full_load_suspend
8.  full_load_limit_list      ┐
9.  full_load_money_flow      │  并行(AKShare)
10. full_load_member          ┘
11. full_load_top_list
12. full_load_margin
13. full_load_hk_hold
14. full_load_holdertrade
15. full_load_finance         (最后,因为最慢)
16. full_load_minute_bar      (可选,极慢)
```

`scripts/update_all.py` —— 日常编排:
```
1. update_calendar (周一才跑)
2. update_basic    (周一才跑)
3. update_daily_bar / update_adj_factor / update_daily_basic / update_index_daily (并行)
4. update_suspend
5. update_limit_list / update_money_flow (并行)
6. update_top_list / update_margin (并行,T+1 数据,需要 19:00 后才有)
7. update_hk_hold
8. update_member (周日才跑)
```

**编排器必须**:
- 每个子任务独立 try/except,单个失败不影响其他
- 失败任务记录到 `data_update_log` 表
- 全部完成后输出汇总报告
- 支持 `--skip` 参数跳过某些子任务

### 7.4 调度器(`scripts/run_scheduler.py`)

**作用**:常驻进程,读 `scheduler_jobs.yaml`,定时调用 `update_*.py` 的 `run()` 函数。

**实现**:基于 APScheduler 的 BlockingScheduler。

**`config/scheduler_jobs.yaml`**:

```yaml
# 调度任务配置
# cron 表达式:分 时 日 月 周
# 周:0=周日, 1=周一, ..., 6=周六

timezone: Asia/Shanghai

jobs:
  # ========== 每个交易日 17:30 ==========
  - id: update_daily_bar
    cron: "30 17 * * 1-5"
    task: scripts.update_daily_bar:run
    enabled: true
    
  - id: update_adj_factor
    cron: "32 17 * * 1-5"
    task: scripts.update_adj_factor:run
    enabled: true
    
  - id: update_daily_basic
    cron: "34 17 * * 1-5"
    task: scripts.update_daily_basic:run
    enabled: true
    
  - id: update_index_daily
    cron: "36 17 * * 1-5"
    task: scripts.update_index_daily:run
    enabled: true
    
  - id: update_suspend
    cron: "38 17 * * 1-5"
    task: scripts.update_suspend:run
    enabled: true
  
  # ========== 每个交易日 17:45 ==========
  - id: update_limit_list
    cron: "45 17 * * 1-5"
    task: scripts.update_limit_list:run
    enabled: true
    
  - id: update_money_flow
    cron: "47 17 * * 1-5"
    task: scripts.update_money_flow:run
    enabled: true
  
  # ========== 每个交易日 19:00(T+1 数据)==========
  - id: update_top_list
    cron: "0 19 * * 1-5"
    task: scripts.update_top_list:run
    enabled: true
    
  - id: update_margin
    cron: "5 19 * * 1-5"
    task: scripts.update_margin:run
    enabled: true
  
  # ========== 每个交易日 21:00 ==========
  - id: update_hk_hold
    cron: "0 21 * * 1-5"
    task: scripts.update_hk_hold:run
    enabled: true
  
  # ========== 每个交易日 21:30 数据校验 ==========
  - id: data_validation
    cron: "30 21 * * 1-5"
    task: data.validator.runner:run_validation
    enabled: true
  
  # ========== 每个交易日 21:45 复盘报告(P1 实现后启用)==========
  - id: daily_review
    cron: "45 21 * * 1-5"
    task: scripts.run_review:run
    enabled: false           # P0 阶段保持 false,P1 完成后改 true
  
  # ========== 每周日 23:00 ==========
  - id: weekly_member_update
    cron: "0 23 * * 0"
    task: scripts.update_member:run
    enabled: true
    
  - id: weekly_basic_update
    cron: "10 23 * * 0"
    task: scripts.update_basic:run
    enabled: true
    
  - id: weekly_calendar_update
    cron: "20 23 * * 0"
    task: scripts.update_calendar:run
    enabled: true
  
  # ========== 每月 1 日凌晨 ==========
  - id: monthly_finance_update
    cron: "0 2 1 * *"
    task: scripts.update_finance:run
    enabled: true
    
  - id: monthly_holdertrade_update
    cron: "0 3 1 * *"
    task: scripts.update_holdertrade:run
    enabled: true

# ========== 失败处理 ==========
on_failure:
  retry: 3
  retry_delay_seconds: 300
  notify: true              # 通过 INotifier 发告警
```

**`scripts/run_scheduler.py` 实现要点**(Hermes 严格遵循):

```python
"""调度器入口。读 scheduler_jobs.yaml,启动 APScheduler,持续运行。"""
import importlib
import sys
import yaml
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from utils.logger import setup_logger
from utils.notifier import get_notifier


def parse_cron(cron_expr: str) -> CronTrigger:
    """解析 5 段式 cron。"""
    parts = cron_expr.split()
    return CronTrigger(
        minute=parts[0], hour=parts[1],
        day=parts[2], month=parts[3], day_of_week=parts[4],
        timezone="Asia/Shanghai",
    )


def resolve_task(task_str: str):
    """解析 'module.path:func_name' 字符串到可调用对象。"""
    module_path, func_name = task_str.split(":")
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def make_safe_runner(task_func, job_id: str, retry: int, notifier):
    """包装任务函数:加重试 + 失败告警。"""
    def runner():
        last_err = None
        for attempt in range(1, retry + 1):
            try:
                logger.info(f"[{job_id}] 第 {attempt}/{retry} 次执行")
                task_func()
                logger.info(f"[{job_id}] 成功")
                return
            except Exception as e:
                last_err = e
                logger.warning(f"[{job_id}] 第 {attempt} 次失败: {e}")
        # 全部失败,告警
        if notifier:
            notifier.send_text(
                title=f"[调度告警] {job_id} 失败",
                content=f"重试 {retry} 次仍失败\n错误: {last_err}",
            )
    return runner


def main() -> int:
    setup_logger(name="scheduler")
    config_path = Path("config/scheduler_jobs.yaml")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    
    notifier = get_notifier() if cfg.get("on_failure", {}).get("notify") else None
    retry = cfg.get("on_failure", {}).get("retry", 3)
    
    sched = BlockingScheduler(timezone=cfg.get("timezone", "Asia/Shanghai"))
    
    for job in cfg["jobs"]:
        if not job.get("enabled", True):
            logger.info(f"跳过已禁用任务: {job['id']}")
            continue
        try:
            task_func = resolve_task(job["task"])
            runner = make_safe_runner(task_func, job["id"], retry, notifier)
            sched.add_job(
                runner,
                trigger=parse_cron(job["cron"]),
                id=job["id"],
                name=job["id"],
                replace_existing=True,
            )
            logger.info(f"加载任务: {job['id']} @ {job['cron']}")
        except Exception as e:
            logger.error(f"加载任务失败 {job['id']}: {e}")
    
    logger.info("调度器启动")
    try:
        sched.start()
    except KeyboardInterrupt:
        logger.info("调度器关闭")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**典型用法**:
```bash
# 前台运行(测试用)
python scripts/run_scheduler.py

# 后台运行
nohup python scripts/run_scheduler.py > logs/scheduler.log 2>&1 &

# 查看进程
ps aux | grep run_scheduler
```

### 7.5 脚本统一模板

所有 `scripts/update_*.py` 必须遵守同一个模板:

```python
"""scripts/update_daily_bar.py - 日线增量更新。"""
import argparse
import sys
from datetime import date, datetime

from loguru import logger

from config.settings import settings
from data.source.factory import get_data_source
from data.storage.factory import get_market_store
from data.updater.daily_bar_updater import DailyBarUpdater
from utils.logger import setup_logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="日线增量更新")
    parser.add_argument("--date", type=str, default=None,
                        help="目标日期 YYYY-MM-DD,默认最近交易日")
    parser.add_argument("--start", type=str, default=None,
                        help="起始日期(范围模式)")
    parser.add_argument("--end", type=str, default=None,
                        help="结束日期(范围模式)")
    parser.add_argument("--ts_codes", type=str, default=None,
                        help="指定股票,逗号分隔")
    parser.add_argument("--force", action="store_true",
                        help="强制覆盖已存在数据")
    return parser.parse_args()


def run(
    target_date: date | None = None,
    start: date | None = None,
    end: date | None = None,
    ts_codes: list[str] | None = None,
    force: bool = False,
) -> int:
    """供调度器调用的入口。无参数时拉最近一个交易日。
    
    Returns:
        受影响行数
    """
    source = get_data_source(settings.primary_data_source)
    store = get_market_store()
    updater = DailyBarUpdater(source, store)
    return updater.update(
        target_date=target_date,
        start=start, end=end,
        ts_codes=ts_codes,
        force=force,
    )


def main() -> int:
    args = parse_args()
    setup_logger(name="update_daily_bar")
    
    target_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date else None
    )
    start = datetime.strptime(args.start, "%Y-%m-%d").date() if args.start else None
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else None
    ts_codes = args.ts_codes.split(",") if args.ts_codes else None
    
    try:
        rows = run(target_date, start, end, ts_codes, args.force)
        logger.info(f"更新完成,影响 {rows} 行")
        return 0
    except Exception as e:
        logger.exception(f"更新失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

**强制规则**:
- 所有脚本必须有 `run()` 函数(供调度器调用,不接 CLI 参数)
- 所有脚本必须有 `main()` 函数(命令行入口,解析 argparse)
- 所有脚本通过工厂拿依赖,不直接 import 实现
- 所有脚本返回 0(成功)或非 0(失败)
- 必须支持 `--help`

`full_load_*.py` 模板类似,但**不接受 `--date`**,只接受 `--start --end --ts_codes`。

### 7.6 README 运维流程模板

把这段直接放到 `README.md`:

```markdown
### 数据运维流程

### 首次部署
\`\`\`bash
bash deploy/setup.sh                       # 装环境 + 起 PostgreSQL/Redis
cp .env.example .env                       # 填 TUSHARE_TOKEN 等敏感配置
vim config/settings.yaml                   # (可选)调整业务参数
python scripts/init_db.py                  # 建表
python scripts/full_load_all.py            # 一键全量初始化(2-4 小时)
\`\`\`

### 日常运维(三选一)

**方式 A:启动调度器(推荐,有常开机器时)**
\`\`\`bash
nohup python scripts/run_scheduler.py > logs/scheduler.log 2>&1 &
\`\`\`
之后所有任务自动按 `config/scheduler_jobs.yaml` 定时执行。

**方式 B:每天手动跑一次**
\`\`\`bash
python scripts/update_all.py
\`\`\`

**方式 C:精准跑某个表**
\`\`\`bash
python scripts/update_daily_bar.py
\`\`\`

### 补数 / 修数

发现某天某表数据缺失:
\`\`\`bash
python scripts/update_daily_bar.py --date 2025-01-15 --force
\`\`\`

补一段日期范围:
\`\`\`bash
python scripts/update_daily_bar.py --start 2025-01-01 --end 2025-01-31 --force
\`\`\`

### 查看运维状态

\`\`\`sql
-- 最近更新记录
SELECT * FROM data_update_log ORDER BY started_at DESC LIMIT 20;

-- 失败的更新
SELECT * FROM data_update_log WHERE status = 'failed' ORDER BY started_at DESC;

-- 数据质量问题
SELECT * FROM data_quality_report 
WHERE check_result != 'pass' 
ORDER BY report_date DESC LIMIT 50;
\`\`\`

### 修改调度时间

编辑 `config/scheduler_jobs.yaml`,改 `cron` 字段,然后重启调度器:
\`\`\`bash
pkill -f run_scheduler
nohup python scripts/run_scheduler.py > logs/scheduler.log 2>&1 &
\`\`\`
```

### 7.7 P0 必须交付的脚本清单

P0 完成时,以下脚本必须全部能跑(都支持 `--help`):

**全量脚本** (16 个):
- `init_db.py`
- `full_load_calendar.py` / `full_load_basic.py`
- `full_load_daily_bar.py` / `full_load_adj_factor.py` / `full_load_daily_basic.py` / `full_load_index_daily.py`
- `full_load_minute_bar.py`
- `full_load_limit_list.py` / `full_load_money_flow.py`
- `full_load_top_list.py` / `full_load_margin.py` / `full_load_hk_hold.py` / `full_load_suspend.py`
- `full_load_finance.py` / `full_load_member.py` / `full_load_holdertrade.py`
- `full_load_all.py`(编排器)

**增量脚本** (15 个):
- `update_calendar.py` / `update_basic.py`
- `update_daily_bar.py` / `update_adj_factor.py` / `update_daily_basic.py` / `update_index_daily.py`
- `update_limit_list.py` / `update_money_flow.py`
- `update_top_list.py` / `update_margin.py` / `update_hk_hold.py` / `update_suspend.py`
- `update_finance.py` / `update_member.py` / `update_holdertrade.py`
- `update_all.py`(编排器)

**调度器** (1 个):
- `run_scheduler.py`

**配置文件** (3 个):
- `config/settings.yaml`
- `config/scheduler_jobs.yaml`
- `config/review_rules.yaml`(P1 用,P0 阶段创建空骨架)

每个脚本都要写对应的单元测试,至少能 `--help` 不报错。

---

## 八、P0 实施细则

### 7.1 P0 任务拆解(Hermes 严格按此顺序)

```
P0.1 实现 utils 工具层
     ├─ utils/logger.py (loguru 配置,按模块分文件)
     ├─ utils/exception.py (自定义异常类)
     ├─ utils/rate_limiter.py (令牌桶限频)
     ├─ utils/retry.py (基于 tenacity 的重试装饰器)
     └─ utils/calendar.py (交易日历工具,先空实现,P0.4 后填充)
     [DONE] → commit

P0.2 实现存储层
     ├─ data/storage/duckdb_store.py (实现 IMarketStore)
     ├─ data/storage/pg_store.py (实现 IMetaStore)
     ├─ data/storage/redis_cache.py (实现 ICache)
     ├─ data/storage/factory.py (工厂)
     └─ scripts/init_db.py (建所有表)
     [DONE] → commit → 用户运行 init_db 验证

P0.3 实现数据源适配器
     ├─ data/source/tushare_source.py (实现 IDataSource)
     ├─ data/source/akshare_source.py (实现 IDataSource)
     ├─ data/source/factory.py (工厂)
     └─ tests/unit/test_*_source.py (mock 测试)
     [DONE] → commit

P0.4 实现增量更新
     ├─ data/updater/init_loader.py (全量初始化)
     ├─ data/updater/daily_updater.py (每日增量)
     ├─ data/updater/finance_updater.py (财务季报)
     └─ data/updater/scheduler.py (调度入口)
     [DONE] → commit → 用户跑全量加载

P0.5 实现校验和复权
     ├─ data/validator/completeness.py
     ├─ data/validator/consistency.py
     ├─ data/validator/anomaly.py
     └─ data/adjust/adjuster.py
     [DONE] → commit

P0.6 实现统一数据 API
     ├─ data/api.py (聚宽风格)
     └─ tests/integration/test_data_api.py
     [DONE] → commit

P0.7 实现 data/updater 业务层
     ├─ data/updater/base.py (BaseUpdater 抽象类)
     ├─ data/updater/daily_bar_updater.py
     ├─ data/updater/adj_factor_updater.py
     ├─ data/updater/daily_basic_updater.py
     ├─ data/updater/index_daily_updater.py
     ├─ data/updater/minute_bar_updater.py
     ├─ data/updater/limit_list_updater.py
     ├─ data/updater/money_flow_updater.py
     ├─ data/updater/top_list_updater.py
     ├─ data/updater/margin_updater.py
     ├─ data/updater/hk_hold_updater.py
     ├─ data/updater/suspend_updater.py
     ├─ data/updater/finance_updater.py
     ├─ data/updater/member_updater.py
     ├─ data/updater/holdertrade_updater.py
     ├─ data/updater/basic_updater.py
     ├─ data/updater/calendar_updater.py
     └─ tests/unit/test_*_updater.py
     [DONE] → commit

P0.8 实现全量脚本
     ├─ scripts/init_db.py
     ├─ scripts/full_load_*.py (16 个,见 7.7)
     └─ scripts/full_load_all.py (编排器)
     [DONE] → commit → 用户跑 full_load_all.py 验证

P0.9 实现增量脚本
     ├─ scripts/update_*.py (15 个,见 7.7)
     └─ scripts/update_all.py (编排器)
     [DONE] → commit → 用户跑 update_all 验证一天

P0.10 实现调度器
      ├─ scripts/run_scheduler.py
      ├─ config/settings.yaml
      ├─ config/scheduler_jobs.yaml (cron 时间表)
      └─ tests/integration/test_scheduler.py
      [DONE] → commit → 用户启动调度器跑半天验证

[GATE_REQUEST] P0 完成,请求 Gate1 通过
```

### 7.2 数据 API 严格签名(Hermes 必须照抄)

```python
# data/api.py
"""统一数据 API,聚宽风格。所有上层模块只通过此 API 取数。"""
from datetime import date
import pandas as pd


def get_price(
    security: str | list[str],
    start_date: str | date,
    end_date: str | date,
    frequency: str = "daily",
    fields: list[str] | None = None,
    fq: str = "pre",
    skip_paused: bool = False,
) -> pd.DataFrame:
    """获取行情数据。"""


def get_fundamentals(
    table: str,  # income / balancesheet / cashflow / fina_indicator
    ts_code: str | list[str],
    start_date: date | None = None,
    end_date: date | None = None,
    fields: list[str] | None = None,
) -> pd.DataFrame:
    """获取基本面数据。"""


def get_index_stocks(index_code: str, date: date | None = None) -> list[str]: ...
def get_industry_stocks(industry: str, date: date | None = None) -> list[str]: ...
def get_concept_stocks(concept: str, date: date | None = None) -> list[str]: ...
def get_trade_days(start_date: date | None = None, end_date: date | None = None) -> list[date]: ...
def get_security_info(ts_code: str) -> dict: ...

def attribute_history(
    security: str,
    count: int,
    unit: str = "1d",
    fields: list[str] | None = None,
    skip_paused: bool = True,
    fq: str = "pre",
) -> pd.DataFrame: ...

def get_money_flow(
    target_type: str,  # concept / industry / stock
    code: str | list[str] | None = None,
    trade_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """获取资金流数据(P1 复盘需要)。"""

def get_limit_pool(
    trade_date: date | None = None,
    kind: str = "U",  # U / D / Z
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """获取涨跌停池(P1 复盘需要)。"""
```

### 7.3 P0 验收标准 (Gate1)

- [ ] 所有 21 张表创建成功
- [ ] `IDataSource` 的所有方法在 Tushare 和 AKShare 适配器中都已实现
- [ ] `IMarketStore` / `IMetaStore` / `ICache` 接口实现完成
- [ ] 全市场 5000+ 只股票 2014-至今日线数据入库
- [ ] 全市场分钟线数据(最近 3 年)入库
- [ ] 财务三张表 + 财务指标完整入库(2010 年至今)
- [ ] 概念/行业板块成分关系完整入库
- [ ] 涨跌停板数据(2020 年至今)完整入库
- [ ] **资金流数据**(板块/个股,2020 年至今)完整入库 - P1 必需
- [ ] 每日定时增量更新跑通一次
- [ ] 数据质量报告显示无缺失、无异常
- [ ] 复权后价格与同花顺对比误差 < 0.1%
- [ ] 单股票 10 年日线查询 < 50ms
- [ ] 1000 股截面数据查询 < 500ms
- [ ] 单元测试覆盖率 ≥ 70%
- [ ] `ruff` / `mypy` 无警告
- [ ] 用户能跑 `python scripts/full_load_all.py` 完成全量初始化
- [ ] 7.7 列出的所有脚本(16 个全量 + 15 个增量 + 1 个调度器)全部可执行,`--help` 都能跑通
- [ ] `scripts/update_all.py --date YYYY-MM-DD` 跑通一天的增量
- [ ] `scripts/update_daily_bar.py --start --end --force` 能精准补漏
- [ ] `config/settings.yaml` / `config/scheduler_jobs.yaml` 就位
- [ ] `scripts/run_scheduler.py` 能启动并加载所有任务,可通过修改 YAML 调整时间无需改代码
- [ ] 调度器在测试环境跑通至少 4 小时,所有 enabled 任务按时触发
- [ ] 调度器失败重试 + 告警机制生效(可手动触发一次模拟失败验证)

**Hermes 完成后输出 `[GATE_REQUEST] P0 完成,请求进入 P1`。**

---

## 九、P1 每日复盘报告

### 8.1 设计目标

每日盘后(15:30 后)自动生成结构化的市场复盘报告,**输出格式参考用户提供的样例图片**。

输出格式:HTML(主) + 长图 PNG(分发用) + PDF(可选)。

### 8.2 报告内容结构

| 节 | 内容 |
|---|---|
| 标题 | YYYY-MM-DD 正式复盘 |
| 顶部摘要 | 一句话总收口(由分析器结合数据生成) |
| 卡片区 | 主线 / 次主线 / 风险边界,各板块 1 行总结 |
| 1. 一句话总收口 | 同顶部摘要展开 |
| 2. 盘型/环境 | 指数表现、宽度、涨跌停/炸板数 |
| 2.5 资金流证据 | 行业/板块流入流出 TOP3、个股流入流出 TOP5 |
| 2.6 情绪运行阶段 | 启动/扩散/分歧/退潮/冰点/修复 + 证据 |
| 3. 上一交易日重点轮动支线现状 | 昨日强势板块今日表现回顾 |
| 4. 主线/次主线/活口/失败轮动/资金撤退方向 | 板块量价、前排名册、代表票、裁定 |

### 8.3 模块详细设计

#### 8.3.1 `review/collector.py` 数据采集

```python
"""复盘数据采集。从 P0 数据库聚合复盘所需数据。"""
from dataclasses import dataclass
from datetime import date
import pandas as pd


@dataclass
class ReviewRawData:
    """复盘原始数据。"""
    trade_date: date
    
    # 指数表现:{"上证指数": {"close": ..., "pct_chg": ...}, ...}
    index_perf: dict[str, dict]
    
    # 市场宽度:{"up": 2746, "down": 2339, "flat": 124, "net": 407}
    breadth: dict
    
    # 涨跌停统计:{"limit_up": 98, "limit_down": 11, "broken": 14, "broken_rate": 0.143}
    limit_stats: dict
    
    # 涨停明细 + 连板梯队
    limit_up_details: pd.DataFrame
    consecutive_limits: list[dict]  # [{"limit_times": 5, "stocks": [...]}, ...]
    
    # 资金流 TOP
    top_industries_in: list[dict]
    top_industries_out: list[dict]
    top_concepts_in: list[dict]
    top_concepts_out: list[dict]
    top_stocks_in: list[dict]
    top_stocks_out: list[dict]
    
    # 强势板块 / 昨日强势 vs 今日表现
    hot_concepts: list[dict]
    prev_hot_review: list[dict]
    
    # 北向资金
    north_flow: dict


class ReviewDataCollector:
    """复盘数据采集器。"""
    
    def collect(self, trade_date: date) -> ReviewRawData:
        """收集指定日期的复盘原始数据。"""
```

#### 8.3.2 `review/analyzer.py` 规则分析

```python
"""复盘分析器,基于规则判定情绪阶段、主线、次主线等。"""
from dataclasses import dataclass


@dataclass
class LineInfo:
    """一条主线/次主线/活口的信息。"""
    name: str                       # 板块名,如 "半导体/芯片链"
    line_type: str                  # main / sub / live / failed / retreat
    money_flow: float               # 净流入(亿)
    pct_chg: float                  # 板块涨幅
    limit_count: int                # 涨停数
    near_limit_count: int           # 近涨停数
    representative_stocks: list[dict]  # 代表票
    leader_stocks: list[dict]       # 前排名册
    verdict: str                    # 裁定文案
    risk_note: str = ""             # 风险备注


@dataclass
class ReviewAnalysis:
    phase: str                      # 启动/扩散/分歧/退潮/冰点/修复
    phase_evidence: dict
    main_lines: list[LineInfo]
    sub_lines: list[LineInfo]
    live_lines: list[LineInfo]
    failed_lines: list[LineInfo]
    retreat_lines: list[LineInfo]
    risk_boundary: str


class ReviewAnalyzer:
    """复盘分析器。所有阈值从 config/review_rules.yaml 读取,严禁硬编码。"""
    
    def analyze(self, raw: ReviewRawData) -> ReviewAnalysis: ...
    def judge_phase(self, raw: ReviewRawData) -> tuple[str, dict]: ...
    def identify_main_lines(self, raw: ReviewRawData) -> list[LineInfo]: ...
    def calc_volume_price_ratio(self, concept: dict) -> float: ...
```

#### 8.3.3 `config/review_rules.yaml` 判定规则

```yaml
phase_thresholds:
  spread:                   # 扩散
    limit_up_min: 80
    broken_rate_max: 0.15
  divergence:               # 分歧扩散
    limit_up_range: [60, 80]
    broken_rate_range: [0.15, 0.25]
  recede:                   # 退潮
    limit_up_max: 60
    broken_rate_min: 0.25
  freeze:                   # 冰点
    limit_up_max: 40
    limit_down_gt_up: true
  recovery:                 # 修复/启动
    limit_up_min: 40
    growth_rate_min: 1.0    # 较前一日翻倍

main_line:
  money_flow_min: 50        # 亿
  limit_count_min: 5
  pct_chg_min: 0.02

sub_line:
  money_flow_range: [30, 50]
  limit_count_range: [3, 5]

retreat_line:
  money_flow_max: -30       # 净流出 ≥ 30 亿

failed_rotation:
  was_strong_yesterday: true
  pct_chg_today_max: -0.02

volume_price_ratio:
  hot_threshold: 0.05       # 5% 资金抱团
  cold_threshold: 0.01      # 1% 资金冷淡
```

#### 8.3.4 `review/narrative.py` 文案生成

```python
"""文案生成器。先用规则模板,后续可换 LLM。"""
from interfaces.llm_provider import ILLMProvider


class NarrativeGenerator:
    """复盘文案生成器。
    
    支持两种模式:
    - rule_template: 基于 Jinja2 模板
    - llm: 调用 LLM 生成
    
    通过 ILLMProvider 注入,无 LLM 时降级到规则模式。
    """
    
    def __init__(self, llm: ILLMProvider | None = None):
        self.llm = llm
    
    def generate_summary(self, raw, analysis) -> str: ...
    def generate_environment(self, raw) -> str: ...
    def generate_fund_evidence(self, raw) -> str: ...
    def generate_phase_section(self, raw, analysis) -> str: ...
    def generate_prev_review(self, raw) -> str: ...
    def generate_line_section(self, line: "LineInfo") -> str: ...
    def generate_risk_boundary(self, raw, analysis) -> str: ...
```

模板放在 `review/templates/`,Jinja2 格式。

#### 8.3.5 `review/renderer/` 报告渲染

实现 `IReportRenderer`,工厂选择渲染器:

- `HTMLRenderer` - 渲染 HTML(主格式),Jinja2 模板 + Tailwind CDN
- `ImageRenderer` - 用 playwright 把 HTML 截成长图
- `PDFRenderer`(可选) - 用 playwright 导出 PDF

P1 复盘报告的图片输出必须匹配确认的参考样式:竖版长图、顶部棕橙渐变封面、2×2 信息卡片、浅米色章节条、适合微信/飞书分享的财经复盘风格。
#### 8.3.6 调度入口

`review/main.py`:

```python
def run_daily_review(trade_date: date | None = None) -> Path:
    """每日复盘主入口。
    
    Args:
        trade_date: 指定日期,默认最近一个交易日
    
    Returns:
        报告 HTML 文件路径
    """
    # 1. collector.collect()
    # 2. analyzer.analyze()
    # 3. narrative.generate_*()
    # 4. renderer.render() → HTML
    # 5. 截图为长图
    # 6. notifier.send_image() (可选)
    # 7. 归档到 reports/YYYY-MM-DD/


### 8.4 P1 任务拆解

```
P1.1 实现接口与 LLM Provider 默认实现
     ├─ review/llm/local_rule_provider.py (规则模板降级)
     └─ tests/unit/test_llm_provider.py
     [DONE] → commit

P1.2 数据采集
     ├─ review/collector.py
     └─ tests/unit/test_collector.py
     [DONE] → commit

P1.3 规则分析
     ├─ review/analyzer.py
     ├─ config/review_rules.yaml
     └─ tests/unit/test_analyzer.py
     [DONE] → commit

P1.4 文案生成与版式约束
     ├─ review/narrative.py
     ├─ review/templates/*.jinja2
     └─ tests/unit/test_narrative.py
     [DONE] → commit

P1.5 报告渲染与长图输出
     ├─ review/renderer/html_renderer.py
     ├─ review/renderer/image_renderer.py
     ├─ review/renderer/templates/report.html.jinja2
     └─ tests/integration/test_renderer.py
     [DONE] → commit

P1.6 调度入口
     ├─ review/main.py
     └─ scripts/run_review.py
     [DONE] → commit

[GATE_REQUEST] P1 完成,请求进入 P2
```

### 8.5 P1 验收标准 (Gate2)

- [ ] `python scripts/run_review.py` 能稳定产出 2026-05-19 这类交易日的正式复盘 Markdown
- [ ] 复盘 Markdown 必须严格包含固定章节:顶部摘要、卡片区、一句话总收口、盘型/环境、资金流证据、情绪运行阶段、上一交易日重点轮动支线现状、主线/次主线/活口/失败轮动/资金撤退方向
- [ ] 复盘图片必须按确认的参考样式输出:竖版长图、顶部棕橙渐变封面、2×2 信息卡片、浅米色章节条、财经复盘风格
- [ ] Markdown 与图片内容必须一致,不得出现图文内容不一致或图片缺章节
- [ ] 主线、次主线、风险边界、资金流证据、情绪阶段等内容必须由 `collector` + `analyzer` 的真实数据驱动,禁止手工拼接空模板
- [ ] 报告自动归档到 `reports/review/` 或约定输出目录
- [ ] 失败降级时,必须保持 Markdown 可读且图片可生成,不得让空数据直接中断流程
- [ ] 单元测试覆盖率 ≥ 70%
- [ ] `ruff` / `mypy` 无警告
- [ ] LLM 不可用时自动降级到规则模板,不报错

---

## 十、P2-P6 概要(详细设计在对应 Phase 开始前展开)

### P2 因子引擎
- 因子接口 `IFactor`,所有因子继承
- 因子库 30+ 因子(量价、基本面、技术、另类、Alpha101)
- 因子分析(IC、IR、分层、衰减)
- 因子合成(加权、正交、中性化)

### P3 回测引擎
- 事件驱动 + 向量化双模式
- 严格对齐 A 股规则
- 与聚宽对比误差 < 1%

### P4 策略引擎 + 风控 + 调度
- 策略 API 全面对齐聚宽
- `ITradeGateway` 抽象,回测/仿真/实盘共用策略代码
- 风控前置
- Ray Actor 多策略并行

### P5 Web 服务
- FastAPI + Streamlit
- Dashboard / 数据浏览 / 回测分析 / 因子分析

### P6 实盘交易
- `PaperGateway`(仿真)+ `QmtGateway`(实盘)
- 仿真盘 2 周后才允许实盘

每阶段开始前,Hermes 必须提交详细任务拆解给用户确认,然后再写代码。

---

## 十一、Hermes 启动指令(摘要)

收到本文档后,**严格按以下流程**:

```
Step 1: 通读本文档,列出疑问点(若有),输出 [QUESTION] 等用户回复

Step 2: 进入 Phase A 工程初始化
        - 创建目录骨架
        - 写 pyproject.toml
        - 写 .env.example (空值,严禁填值!)
        - 写 docker-compose.yml
        - 写 setup.sh
        - 实现 utils/* 工具层
        - 定义所有 interfaces/* 抽象接口骨架
        - 输出 [GATE_REQUEST] Phase A 完成

Step 3: 等用户回复 [GATE_PASS],进入 P0
        按 7.1 顺序逐子模块实现
        每子模块完成 → commit + [DONE]
        全部完成 → [GATE_REQUEST] P0 完成

Step 4: 等用户回复 [GATE_PASS],进入 P1
        按 8.4 顺序实现
        全部完成 → [GATE_REQUEST] P1 完成

Step 5+: 后续阶段开始前,先输出详细任务拆解,等用户确认
```

**严禁**:
- 跳过任何 Gate
- 在 `.env` / 代码里填真实 token
- 添加文档没要求的功能
- 在 P0 完成前做 P1+
- 在自检清单未全 ✓ 时 commit

---

## 十二、给用户的话(本文档使用方式)

1. **第一次给 Hermes**:把整份文档作为 system prompt 或 readme 传给它,让它先复述「Phase A 第一步要做什么」「禁止行为有哪些」「Gate1 验收标准是什么」,确认理解正确再让它动手
2. **每次开新会话**:重新喂一遍本文档,Hermes 没有跨会话记忆
3. **每次 Gate**:Hermes 输出 `[GATE_REQUEST]`,你 review 代码后回复 `[GATE_PASS]` 才能继续
4. **遇到 `[ALERT]` / `[QUESTION]`**:停下来给决策,不要让它自己拍板
5. **填 .env**:`cp .env.example .env`,把 TUSHARE_TOKEN 等填进去
6. **修改判定规则**:P1 的判定阈值在 `config/review_rules.yaml`,你可以随时改

---

文档结束。
