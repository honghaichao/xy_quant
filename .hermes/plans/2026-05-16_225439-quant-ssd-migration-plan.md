# xy_quant 数据迁移到 quant-ssd 方案

## 目标

把当前 `~/workspace/xy_quant` 中的数据类资产迁移到新盘 `/Volumes/quant-ssd`，在尽量不改业务代码的前提下，完成：

1. `xy_quant` 大体量数据迁移
2. 运行路径保持稳定或最小改动
3. 支持回滚
4. 支持后续持续扩容与备份

## 当前现场结论

### 已确认

- 新盘挂载点：`/Volumes/quant-ssd`
- 新盘容量：`1.9Ti`
- 当前项目路径：`~/workspace/xy_quant`
- 当前项目总占用：约 `119G`
- 其中主要空间占用：
  - `data_store/`：`118G`
  - `logs/`：`253M`
  - `reports/`：`2.9M`
  - `tmp/`：`1.5M`
- 当前代码里已发现的本地数据路径约定：
  - `config/settings.py:17` 默认 `duckdb_path = "./data_store/market.duckdb"`
  - `config/settings.py:33` 默认 `log_dir = "./logs"`
  - `scripts/report_recap_data.py` / `scripts/verify_minute_bar_coverage.py` 里直接写死 `ROOT / "data_store" / "market.duckdb"`

### 关键判断

当前真正的大头是 `data_store/`，因此迁移核心不是“整个项目搬盘”，而是：

- **代码继续放系统盘**（体积小、开发稳定）
- **数据目录搬到 quant-ssd**（容量扩展明显）
- 对代码侧通过 **软链接或显式配置** 维持兼容

这是风险最低、收益最高的方案。

## 推荐方案

采用 **“代码留原位 + 数据目录外置到 quant-ssd + 项目内软链接兼容”** 的两阶段方案。

### 方案结构

建议在新盘建立统一量化根目录：

```text
/Volumes/quant-ssd/xy_quant/
├── data_store/
├── logs/
├── reports/
├── backups/
└── snapshots/
```

项目内仍保留原路径语义：

```text
~/workspace/xy_quant/
├── data_store -> /Volumes/quant-ssd/xy_quant/data_store
├── logs       -> /Volumes/quant-ssd/xy_quant/logs
├── reports    -> /Volumes/quant-ssd/xy_quant/reports
```

这样可以最大限度兼容现有相对路径实现，避免立即大改脚本。

## 分阶段迁移计划

## Phase 0：迁移前盘点与冻结

### 目标

确认哪些进程正在读写 `xy_quant` 数据，避免拷贝过程中数据不一致。

### 步骤

1. 盘点占用进程
   - 查 `xy_quant` 相关 Python / scheduler / 数据更新任务
   - 查是否有 DuckDB 文件正在被打开
2. 暂停所有写入任务
   - 日线增量
   - 分钟线回补
   - 定时复盘
   - 任何写 `data_store/`、`logs/`、`reports/` 的脚本
3. 做一次迁移前快照记录
   - `du -sh data_store logs reports`
   - 记录 `market.duckdb` 文件大小、修改时间

### 验收

- 迁移窗口内无后台写入
- 当前数据规模已记录，可用于迁移后核对

## Phase 1：新盘目录初始化

### 目标

在 quant-ssd 上建立标准目录结构和权限。

### 建议目录

```bash
mkdir -p /Volumes/quant-ssd/xy_quant/{data_store,logs,reports,backups,snapshots}
```

### 说明

- `data_store/`：主数据资产
- `logs/`：运行日志
- `reports/`：复盘报告/验证报告
- `backups/`：迁移前后备份
- `snapshots/`：后续可放阶段性归档

### 验收

- 目录存在
- 当前用户对目录有读写权限
- 新盘剩余空间满足未来 2~3 倍增长

## Phase 2：首次全量复制

### 目标

先复制一份完整数据到新盘，不立刻切流。

### 推荐方式

优先用 `rsync` 做保留属性、可断点续传的拷贝：

```bash
rsync -aH --info=progress2 ~/workspace/xy_quant/data_store/ /Volumes/quant-ssd/xy_quant/data_store/
rsync -aH --info=progress2 ~/workspace/xy_quant/logs/ /Volumes/quant-ssd/xy_quant/logs/
rsync -aH --info=progress2 ~/workspace/xy_quant/reports/ /Volumes/quant-ssd/xy_quant/reports/
```

### 原因

- 比 Finder 拖拽更可靠
- 中断后可续传
- 可二次增量同步
- 便于核对

### 验收

- 拷贝完成无报错
- 新旧目录文件数、总体积基本一致

## Phase 3：数据一致性校验

### 目标

确认新盘副本可直接替代旧目录。

### 校验维度

1. 目录体积校验
   - `du -sh`
2. 文件数量校验
   - `find ... | wc -l`
3. DuckDB 主文件校验
   - `market.duckdb` 文件大小一致
   - 必要时做哈希校验
4. 功能校验
   - 用只读脚本连接新盘上的 DuckDB
   - 跑 1~2 个现有校验脚本，确认能正常读数据

### 推荐额外校验

对这些脚本做定点验证：

- `scripts/verify_minute_bar_coverage.py`
- `scripts/report_recap_data.py`

若它们仍依赖项目内相对路径，则先不要直接改代码，可在切流后通过软链接验证。

### 验收

- 新盘数据可正常读取
- 至少 2 个现有脚本可对新盘数据读成功

## Phase 4：切流方式选择

推荐优先级如下：

### 方案 A（推荐）：项目内软链接切流

#### 做法

1. 旧目录改名备份
2. 建立软链接

示意：

```bash
mv ~/workspace/xy_quant/data_store ~/workspace/xy_quant/data_store.bak
ln -s /Volumes/quant-ssd/xy_quant/data_store ~/workspace/xy_quant/data_store
```

`logs/`、`reports/` 同理。

#### 优点

- 兼容现有 `./data_store/...` 相对路径
- 代码几乎不用改
- 切换快，回滚快

#### 风险

- 个别脚本若显式判断真实路径，可能需要适配
- 开发者需要知道这里是链接，不是实体目录

### 方案 B：改配置显式指向新盘

#### 做法

把 `.env` 中路径改为绝对路径，例如：

- `DUCKDB_PATH=/Volumes/quant-ssd/xy_quant/data_store/market.duckdb`
- `LOG_DIR=/Volumes/quant-ssd/xy_quant/logs`

并逐步清理代码里写死的 `ROOT / "data_store" / "market.duckdb"`。

#### 优点

- 长期结构更清晰
- 配置与存储位置显式解耦

#### 风险

- 你当前已有脚本直接写死相对路径，切换前需要补代码
- 比软链接方案实施成本更高

### 最终建议

- **短期落地：先用方案 A（软链接）**
- **中期治理：再推进方案 B（配置化/路径治理）**

## Phase 5：切流后运行验证

### 目标

确认 `xy_quant` 已实际从 quant-ssd 读写。

### 验证项

1. 运行一个只读数据脚本
2. 运行一个会写日志的脚本
3. 确认新日志落到 `/Volumes/quant-ssd/xy_quant/logs`
4. 确认 DuckDB 最近修改时间已发生在新盘文件上
5. 确认旧目录不再增长

### 验收

- 读写都落在新盘
- 项目功能无异常
- 系统盘空间明显释放

## Phase 6：观察期与清理

### 目标

保留回滚能力，稳定后再删旧数据。

### 建议

- 保留旧目录备份 `data_store.bak` 至少 3~7 天
- 观察期间每日记录：
  - DuckDB 文件增长
  - 日志写入
  - 校验脚本执行情况
- 确认稳定后删除旧备份

### 验收

- 连续数天运行正常
- 无脚本仍依赖旧物理目录
- 系统盘旧备份可安全删除

## 代码侧需要同步治理的点

### 已发现的硬编码/默认路径点

1. `config/settings.py`
   - `duckdb_path = "./data_store/market.duckdb"`
   - `log_dir = "./logs"`
2. `scripts/report_recap_data.py`
   - `ROOT / "data_store" / "market.duckdb"`
3. `scripts/verify_minute_bar_coverage.py`
   - `ROOT / "data_store" / "market.duckdb"`

### 治理建议

#### 第一阶段（迁移当天）

不改业务代码，先靠软链接兼容。

#### 第二阶段（迁移稳定后）

把数据路径统一收口到配置层，例如：

- 所有脚本从 `config.settings.settings` 获取 `duckdb_path`
- 所有日志目录从 `settings.log_dir` 获取
- 后续若新增 `report_dir` / `snapshot_dir`，也统一配置化

### 设计原则

- 业务代码不要再直接拼 `ROOT / "data_store"`
- 路径统一从配置层注入
- 这样未来再次换盘、NAS、外置盘时无需再改脚本

## 推荐目录设计（长期版）

建议未来把 `xy_quant` 拆成“代码根”和“数据根”两个概念：

### 代码根

```text
~/workspace/xy_quant
```

### 数据根

```text
/Volumes/quant-ssd/xy_quant
```

### 建议新增配置概念

- `XY_QUANT_DATA_ROOT=/Volumes/quant-ssd/xy_quant`
- `DUCKDB_PATH=${XY_QUANT_DATA_ROOT}/data_store/market.duckdb`
- `LOG_DIR=${XY_QUANT_DATA_ROOT}/logs`
- `REPORT_DIR=${XY_QUANT_DATA_ROOT}/reports`

这样后续：

- 本地开发
- 外接 SSD
- NAS
- Docker volume

都能沿用同一套结构。

## 风险与对策

### 风险 1：迁移过程中仍有进程写库

- 对策：迁移前冻结任务，切流前再做一次增量 rsync

### 风险 2：DuckDB 文件复制时不一致

- 对策：
  - 停写后复制
  - 切流前做第二次 rsync
  - 切流后先跑只读校验

### 风险 3：脚本里存在更多硬编码路径

- 对策：迁移后补一次全仓搜索：`data_store` / `logs` / `reports` / `market.duckdb`

### 风险 4：外接盘偶发断连

- 对策：
  - 将 quant-ssd 作为“数据盘”而非“代码盘”
  - 加启动前检测：若数据盘未挂载则阻断任务启动

### 风险 5：APFS 外置盘权限/属主问题

- 对策：迁移完成后实际做一次读写验证，不只看文件存在

## 推荐实施顺序（最实用版本）

1. 停止 `xy_quant` 所有写入任务
2. 在 `/Volumes/quant-ssd/xy_quant/` 建目录
3. 全量 rsync `data_store/ logs/ reports/`
4. 做体积/文件数/主文件校验
5. 再做一次增量 rsync
6. 将项目内旧目录改名为 `.bak`
7. 建立软链接
8. 跑 2 个现有脚本验证读写
9. 观察 3~7 天
10. 删除旧备份

## 建议你最终采用的落地策略

### 推荐结论

**不要把整个 `xy_quant` 项目直接整体搬去 quant-ssd。**

更优方案是：

- `~/workspace/xy_quant` 代码保留在原位
- 只把 `data_store/` 为主的数据资产迁到 `/Volumes/quant-ssd/xy_quant/`
- 用软链接先平滑切换
- 稳定后再把路径治理做成配置化

这样：

- 风险最小
- 兼容现有代码最多
- 回滚最快
- 系统盘释放空间最明显

## 后续可直接执行的两个子任务

如果下一步进入执行，我建议按这个顺序做：

1. **先做迁移前盘点脚本**
   - 自动统计目录大小、文件数、打开句柄、写入进程
2. **再做正式迁移执行脚本**
   - 建目录、rsync、校验、切软链接、输出迁移报告

这两个脚本完成后，后续同类迁移可以重复执行。