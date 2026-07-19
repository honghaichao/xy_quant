# 开发约定

- 严格按 `PLAN.md` 执行，不跨 Gate
- 禁止在代码中硬编码 token、账号、密码、绝对路径
- 禁止使用 `print`，统一使用 `loguru.logger`
- 禁止裸 `except:` 或 `except Exception:`
- SQL 必须参数化，禁止字符串拼接
- 所有 public 函数必须提供 docstring
- 所有函数必须有 type hints
- 新增依赖必须先由用户确认
- 用户未回复 `[GATE_PASS]` 前不得进入下一阶段
