"""策略加载器 — importlib 加载零 import 的聚宽策略文件并注入命名空间。"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

OPTIONAL_HOOKS = (
    "before_trading_start", "handle_data", "after_trading_end",
    "process_initialize", "after_code_changed", "on_strategy_end",
)


class StrategyModule:
    """加载后的策略：module + hooks。"""

    def __init__(self, module: types.ModuleType):
        self.module = module
        if not hasattr(module, "initialize"):
            raise ValueError(f"策略 {module.__name__} 缺少 initialize(context) 函数")
        self.initialize = module.initialize
        for hook in OPTIONAL_HOOKS:
            setattr(self, hook, getattr(module, hook, None))


def load_strategy(module_path: str, namespace: dict[str, Any]) -> StrategyModule:
    """加载策略模块。

    module_path 支持两种形式：
      - 点分模块名 "strategies.jq.caimadama"
      - 文件路径 "/path/to/strategy.py"
    namespace 在 exec 前写入模块 __dict__，策略源码零 import 即可用聚宽 API。
    """
    if module_path.endswith(".py") or "/" in module_path:
        file_path = Path(module_path)
        mod_name = f"jq_strategy_{file_path.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, file_path)
    else:
        spec = importlib.util.find_spec(module_path)
        mod_name = module_path
    if spec is None or spec.loader is None:
        raise ImportError(f"无法定位策略模块: {module_path}")

    module = importlib.util.module_from_spec(spec)
    module.__dict__.update(namespace)
    # 先注册再执行，允许策略内部（罕见地）自引用
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return StrategyModule(module)
